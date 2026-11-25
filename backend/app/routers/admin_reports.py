"""Operations: catalogue sync, flagged and hard-to-reach citations, usage, imports.

Needs reports.view somewhere; everything is limited to the lists where the
viewer holds it (a department librarian sees their department). Clicks are
counted anonymously (app/routers/go.py), so these are counts, never people.
"""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.ingest.bulk import JOB_TYPE as IMPORT_JOB
from app.ingest.sync import SYNC_JOB
from app.models.models import (
    BackgroundJob,
    Citation,
    CitationEvent,
    LibrarySource,
    LinkClick,
    ListSection,
    ReadingList,
    User,
)
from app.services import access
from app.services import lists_service as svc

router = APIRouter()

WINDOW_DAYS = 30
FLAGGED = ("missing", "suppressed")


async def reports_viewer(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    if not (await access.load_grants(db, user)).anywhere("reports.view"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission required: reports.view")
    return user


class SyncStatus(BaseModel):
    connected: bool  # an active Alma connection
    last_run_at: datetime | None = None
    last_status: str | None = None  # completed | failed
    checked: int | None = None
    updated: int | None = None
    flagged: int | None = None
    error: str | None = None
    can_run: bool = False


class Overview(BaseModel):
    lists_published: int
    lists_draft: int
    citations: int
    library_records: int
    flagged: int
    clicks: int  # last 30 days
    direct_clicks: int  # went straight to the resource (not a fallback page)


class CitationRow(BaseModel):
    citation_id: uuid.UUID
    title: str
    list_id: uuid.UUID
    list_title: str
    section_title: str


class FlaggedRow(CitationRow):
    status: str
    since: datetime | None = None


class ReachRow(CitationRow):
    clicks: int
    fallback_clicks: int


class TopList(BaseModel):
    list_id: uuid.UUID
    list_title: str
    clicks: int


class TopCitation(CitationRow):
    clicks: int


class ImportRow(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    list_id: uuid.UUID | None
    list_title: str | None
    total: int
    added: int | None
    by: str | None


class Reports(BaseModel):
    window_days: int
    overview: Overview
    sync: SyncStatus
    flagged: list[FlaggedRow]
    hard_to_reach: list[ReachRow]
    top_lists: list[TopList]
    top_citations: list[TopCitation]
    imports: list[ImportRow]


@router.get("/reports", response_model=Reports, summary="Operations and usage")
async def reports(user: User = Depends(reports_viewer), db: AsyncSession = Depends(get_db)):
    grants = await access.load_grants(db, user)
    list_ids = (await svc.visible_lists_query(db, user, "reports.view")).with_only_columns(ReadingList.id).scalar_subquery()
    in_scope = ReadingList.id.in_(list_ids)
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)

    def citation_rows(*columns):
        return (
            select(Citation.id, Citation.title, ReadingList.id, ReadingList.title, ListSection.title, *columns)
            .join(Citation.section)
            .join(ListSection.reading_list)
            .where(in_scope)
        )

    published = await db.scalar(select(func.count()).select_from(ReadingList).where(in_scope, ReadingList.is_published.is_(True)))
    drafts = await db.scalar(select(func.count()).select_from(ReadingList).where(in_scope, ReadingList.is_published.is_(False)))
    citation_count, bound, flagged_count = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Citation.source_system == "alma", func.coalesce(Citation.source_status, "ok") != "unlinked"),
                func.count().filter(Citation.source_system == "alma", Citation.source_status.in_(FLAGGED)),
            )
            .select_from(Citation)
            .join(Citation.section)
            .join(ListSection.reading_list)
            .where(in_scope)
        )
    ).one()
    clicks, direct = (
        await db.execute(
            select(func.count(), func.count().filter(LinkClick.resolved_by != "fallback"))
            .where(LinkClick.reading_list_id.in_(list_ids), LinkClick.clicked_at >= since)
        )
    ).one()

    # Catalogue sync (organization-wide)
    alma = await db.scalar(
        select(LibrarySource.id).where(
            LibrarySource.organization_id == user.organization_id, LibrarySource.kind == "alma", LibrarySource.is_active.is_(True)
        )
    )
    last = await db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.job_type == SYNC_JOB, BackgroundJob.payload["organization_id"].astext == str(user.organization_id))
        .order_by(BackgroundJob.completed_at.desc().nulls_last())
        .limit(1)
    )
    result = (last.result or {}) if last else {}
    sync = SyncStatus(
        connected=alma is not None,
        last_run_at=last.completed_at if last else None,
        last_status=last.status if last else None,
        checked=result.get("checked"),
        updated=result.get("updated"),
        flagged=result.get("flagged"),
        error=last.error if last else None,
        can_run=alma is not None and grants.organization_wide("settings.manage"),
    )

    # Library records gone or hidden, newest first
    latest_event = (
        select(func.max(CitationEvent.occurred_at))
        .where(CitationEvent.citation_id == Citation.id, CitationEvent.kind.in_(FLAGGED))
        .correlate(Citation)
        .scalar_subquery()
    )
    flagged = [
        FlaggedRow(citation_id=r[0], title=r[1], list_id=r[2], list_title=r[3], section_title=r[4], status=r[5], since=r[6])
        for r in await db.execute(
            citation_rows(Citation.source_status, latest_event)
            .where(Citation.source_system == "alma", Citation.source_status.in_(FLAGGED))
            .order_by(latest_event.desc().nulls_last())
            .limit(100)
        )
    ]

    # Clicked, but mostly couldn't go straight to the resource
    per_citation = (
        select(
            LinkClick.citation_id,
            func.count().label("clicks"),
            func.count().filter(LinkClick.resolved_by == "fallback").label("fallback"),
        )
        .where(LinkClick.reading_list_id.in_(list_ids), LinkClick.clicked_at >= since)
        .group_by(LinkClick.citation_id)
        .subquery()
    )
    hard = [
        ReachRow(citation_id=r[0], title=r[1], list_id=r[2], list_title=r[3], section_title=r[4], clicks=r[5], fallback_clicks=r[6])
        for r in await db.execute(
            citation_rows(per_citation.c.clicks, per_citation.c.fallback)
            .join(per_citation, per_citation.c.citation_id == Citation.id)
            .where(per_citation.c.fallback * 2 >= per_citation.c.clicks, per_citation.c.fallback > 0)
            .order_by(per_citation.c.fallback.desc())
            .limit(50)
        )
    ]
    top_citations = [
        TopCitation(citation_id=r[0], title=r[1], list_id=r[2], list_title=r[3], section_title=r[4], clicks=r[5])
        for r in await db.execute(
            citation_rows(per_citation.c.clicks)
            .join(per_citation, per_citation.c.citation_id == Citation.id)
            .order_by(per_citation.c.clicks.desc())
            .limit(10)
        )
    ]
    top_lists = [
        TopList(list_id=r[0], list_title=r[1], clicks=r[2])
        for r in await db.execute(
            select(ReadingList.id, ReadingList.title, func.count())
            .join(LinkClick, LinkClick.reading_list_id == ReadingList.id)
            .where(in_scope, LinkClick.clicked_at >= since)
            .group_by(ReadingList.id, ReadingList.title)
            .order_by(func.count().desc())
            .limit(10)
        )
    ]

    # Recent bulk imports into lists in scope
    import_rows = await db.execute(
        select(BackgroundJob, ReadingList.title, User.display_name)
        .outerjoin(ReadingList, cast(ReadingList.id, Text) == BackgroundJob.payload["reading_list_id"].astext)
        .outerjoin(User, User.id == BackgroundJob.created_by)
        .where(BackgroundJob.job_type == IMPORT_JOB, in_scope)
        .order_by(BackgroundJob.created_at.desc())
        .limit(20)
    )
    imports = [
        ImportRow(
            id=job.id, status=job.status, created_at=job.created_at,
            list_id=uuid.UUID(job.payload["reading_list_id"]) if job.payload.get("reading_list_id") else None,
            list_title=title, total=(job.result or {}).get("total", 0), added=(job.result or {}).get("added"), by=by,
        )
        for job, title, by in import_rows
    ]

    return Reports(
        window_days=WINDOW_DAYS,
        overview=Overview(
            lists_published=published or 0, lists_draft=drafts or 0, citations=citation_count, library_records=bound,
            flagged=flagged_count, clicks=clicks, direct_clicks=direct,
        ),
        sync=sync,
        flagged=flagged,
        hard_to_reach=hard,
        top_lists=top_lists,
        top_citations=top_citations,
        imports=imports,
    )


def enqueue_sync(organization_id: uuid.UUID) -> None:
    """Hand the sync to the worker (replaced in tests)."""
    from app.tasks.sync_tasks import sync_catalogue_for

    sync_catalogue_for.delay(str(organization_id))


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, summary="Check the catalogue now")
async def sync_now(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Start the catalogue sync for this organization (otherwise it runs nightly)."""
    if not (await access.load_grants(db, user)).organization_wide("settings.manage"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission required: settings.manage")
    alma = await db.scalar(
        select(LibrarySource.id).where(
            LibrarySource.organization_id == user.organization_id, LibrarySource.kind == "alma", LibrarySource.is_active.is_(True)
        )
    )
    if alma is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Alma first (Library connections)")
    enqueue_sync(user.organization_id)
    return {"status": "queued"}
