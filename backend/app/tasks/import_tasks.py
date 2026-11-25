import asyncio
import logging
from datetime import UTC, datetime

from app.importers import get_handler
from app.importers.base import NormalizationError
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_import_job(self, job_id: str):
    """
    Process a citation import job.

    Flow:
    1. Load job from DB
    2. Instantiate the appropriate handler (z3950, manual, etc.)
    3. Fetch raw records from source
    4. Normalize each record to CitationDraft
    5. Assess quality (confidence score + warnings)
    6. Write import_items to DB
    7. Broadcast progress via WebSocket
    8. Set job status to 'awaiting_review' on completion

    Row-level errors don't abort the job — a failed row becomes an
    import_item with confidence_score=0 and a warning.
    """
    try:
        asyncio.run(_process_import_job(job_id))
    except Exception as exc:
        logger.exception("Import job %s failed: %s", job_id, exc)
        raise self.retry(exc=exc) from exc


async def _process_import_job(job_id: str):
    from app.database import AsyncSessionLocal
    from app.models.models import BackgroundJob, ImportItem

    async with AsyncSessionLocal() as db:
        job = await db.get(BackgroundJob, job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = "processing"
        job.started_at = datetime.now(UTC)
        await db.commit()

        _broadcast(job.payload.get("list_id"), {
            "type": "import.progress",
            "job_id": job_id,
            "status": "processing",
        })

        handler = get_handler(job.job_type.replace("import_", ""))
        processed = 0
        failed = 0

        async for raw_record in handler.fetch(job.payload):
            try:
                draft = handler.normalize(raw_record)
                score, warnings = handler.assess_quality(draft)

                item = ImportItem(
                    import_job_id=job_id,
                    raw_data=raw_record.data,
                    source_identifier=raw_record.data.get("id") or raw_record.data.get("doi"),
                    normalized_data=draft.__dict__,
                    confidence_score=score,
                    warnings=warnings,
                    status="pending_review",
                    sort_order=processed,
                )
                db.add(item)
                processed += 1

            except NormalizationError as e:
                logger.warning("Normalization failed for record in job %s: %s", job_id, e)
                item = ImportItem(
                    import_job_id=job_id,
                    raw_data=raw_record.data,
                    normalized_data={},
                    confidence_score=0.0,
                    warnings=[f"normalization_error: {str(e)}"],
                    status="pending_review",
                    sort_order=processed,
                )
                db.add(item)
                failed += 1

            if processed % 5 == 0:
                await db.commit()
                _broadcast(job.payload.get("list_id"), {
                    "type": "import.progress",
                    "job_id": job_id,
                    "processed": processed,
                    "failed": failed,
                })

        job.status = "awaiting_review"
        job.completed_at = datetime.now(UTC)
        job.result = {"processed": processed, "failed": failed}
        await db.commit()

        _broadcast(job.payload.get("list_id"), {
            "type": "import.ready_for_review",
            "job_id": job_id,
            "processed": processed,
            "failed": failed,
        })

        logger.info("Import job %s complete: %d processed, %d failed", job_id, processed, failed)


def _broadcast(list_id: str | None, message: dict):
    """Broadcast a WebSocket message to all subscribers of a list."""
    # TODO: implement via Redis pub/sub → WebSocket manager
    logger.debug("WS broadcast list=%s: %s", list_id, message)


@celery_app.task
def match_bulk_import(job_id: str) -> None:
    """Match a bulk import's entries (app/ingest/bulk.py)."""
    asyncio.run(_match_bulk_import(job_id))


async def _match_bulk_import(job_id: str) -> None:
    import uuid

    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.ingest.bulk import run_matching
    from app.ingest.resolvers import ResolveContext
    from app.ingest.sources import context_for
    from app.models.models import BackgroundJob
    from app.services.credentials import CredentialError

    # Fresh engine per run: each asyncio.run() is a new event loop
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            job = await db.get(BackgroundJob, uuid.UUID(job_id))
            if job is None:
                return
            async with httpx.AsyncClient(timeout=20.0) as http:
                try:
                    ctx = await context_for(db, uuid.UUID(job.payload["organization_id"]), http)
                except CredentialError:
                    logger.exception("Library source keys can't be decrypted; matching with open sources only")
                    ctx = ResolveContext(http=http)
                try:
                    await run_matching(db, job.id, ctx)
                except Exception as exc:
                    logger.exception("Bulk import %s failed", job_id)
                    await db.rollback()
                    job = await db.get(BackgroundJob, job.id)
                    job.status, job.error = "failed", str(exc)[:500]
                    await db.commit()
    finally:
        await engine.dispose()
