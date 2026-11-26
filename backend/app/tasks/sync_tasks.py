"""Scheduled catalogue sync (see app/ingest/sync.py)."""
import asyncio
import logging
import uuid

import httpx
from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.ingest.sources import context_for
from app.ingest.sync import sync_organization
from app.models.models import LibrarySource
from app.services.credentials import CredentialError
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    # Overnight (UTC), when Alma's API is quietest
    "catalogue-sync-daily": {"task": "app.tasks.sync_tasks.sync_catalogue", "schedule": crontab(hour=7, minute=15)},
}


@celery_app.task
def sync_catalogue() -> dict:
    """Every organization with an active Alma connection (nightly)."""
    return asyncio.run(_sync())


@celery_app.task
def sync_catalogue_for(organization_id: str) -> dict:
    """One organization, now (an administrator's Sync now)."""
    return asyncio.run(_sync(uuid.UUID(organization_id)))


async def _sync(only: uuid.UUID | None = None) -> dict:
    # A fresh engine per run: each asyncio.run() is a new event loop, and pooled
    # asyncpg connections can't move between loops
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    results: dict[str, dict] = {}
    try:
        async with sessions() as db:
            query = select(LibrarySource.organization_id).where(
                LibrarySource.kind == "alma", LibrarySource.is_active.is_(True)
            )
            if only is not None:
                query = query.where(LibrarySource.organization_id == only)
            org_ids = list(await db.scalars(query))
        async with httpx.AsyncClient(timeout=30.0) as http:
            for org_id in org_ids:
                async with sessions() as db:
                    try:
                        ctx = await context_for(db, org_id, http)
                    except CredentialError:
                        logger.exception("Alma key for org %s can't be decrypted; skipping sync", org_id)
                        continue
                    report = await sync_organization(db, org_id, ctx)
                    await db.commit()
                    results[str(org_id)] = report.__dict__
    finally:
        await engine.dispose()
    return results
