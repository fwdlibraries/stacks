"""Catalogue sync: keep citations bound to Alma records in step with the catalogue.

Library metadata is authoritative, so changes are applied automatically (no
approval step) and logged as citation events. Instructor fields (required,
notes, placement) are never touched. Records that disappear from Alma or are
hidden from discovery are flagged for staff; they come back to 'ok' by
themselves if the record returns.

Runs daily from Celery beat (app/tasks/sync_tasks.py), or on demand with
`python -m app.cli sync-catalogue`.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.candidate import SourceError
from app.ingest.fields import SOURCE_FIELDS, UnusableRecord, citation_fields
from app.ingest.resolvers import ResolveContext, alma
from app.models.models import (
    Citation,
    CitationEvent,
    College,
    CourseTemplate,
    Department,
    ListSection,
    ReadingList,
)

logger = logging.getLogger(__name__)

# Citations checked per organization per run, oldest-checked first. Alma's API
# allows ~100 records per call, so the default is 10 calls a day.
DEFAULT_BATCH = 1000


@dataclass
class SyncReport:
    checked: int = 0
    updated: int = 0
    unchanged: int = 0
    flagged: int = 0  # newly missing or suppressed
    restored: int = 0
    skipped: int = 0  # unreadable records, left as they were
    errors: list[str] = field(default_factory=list)


def _jsonable(value):
    if hasattr(value, "value"):  # enums
        return value.value
    return value


async def bound_citations(db: AsyncSession, organization_id: uuid.UUID, limit: int) -> list[Citation]:
    return list(
        await db.scalars(
            select(Citation)
            .join(Citation.section)
            .join(ListSection.reading_list)
            .join(ReadingList.course_template)
            .join(CourseTemplate.department)
            .join(Department.college)
            .where(
                College.organization_id == organization_id,
                Citation.source_system == "alma",
                or_(Citation.source_status.is_(None), Citation.source_status != "unlinked"),
            )
            .order_by(Citation.source_synced_at.asc().nulls_first())
            .limit(limit)
        )
    )


def _apply(citation: Citation, fields: dict) -> dict:
    """Set changed source fields; returns {field: [old, new]} for the log."""
    changes = {}
    for name in SOURCE_FIELDS:
        new = fields[name]
        old = getattr(citation, name)
        if (old or None) != (new or None):
            changes[name.rstrip("_")] = [_jsonable(old), _jsonable(new)]
            setattr(citation, name, new)
    return changes


async def sync_organization(
    db: AsyncSession, organization_id: uuid.UUID, ctx: ResolveContext, *, limit: int = DEFAULT_BATCH
) -> SyncReport:
    report = SyncReport()
    if "alma" not in ctx.sources:
        return report
    citations = await bound_citations(db, organization_id, limit)
    if not citations:
        return report

    try:
        records = await alma.fetch_many([c.source_identifier for c in citations if c.source_identifier], ctx)
    except SourceError as exc:
        # Alma unreachable or the key rejected: change nothing, try again next run
        report.errors.append(str(exc))
        return report

    now = datetime.now(UTC)
    for citation in citations:
        report.checked += 1
        mms_id = citation.source_identifier or ""
        previous = citation.source_status or "ok"

        if mms_id not in records:
            if previous != "missing":
                citation.source_status = "missing"
                db.add(CitationEvent(citation_id=citation.id, kind="missing", source_system="alma"))
                report.flagged += 1
            else:
                report.unchanged += 1
            citation.source_synced_at = now
            continue

        candidate = records[mms_id]
        if candidate is None:
            report.skipped += 1
            continue
        try:
            fields = citation_fields(candidate)
        except UnusableRecord:
            report.skipped += 1
            continue

        changes = _apply(citation, fields)
        if changes:
            citation.raw_import_data = candidate.raw
            db.add(CitationEvent(citation_id=citation.id, kind="updated", source_system="alma", details=changes))
            report.updated += 1

        status = "suppressed" if alma.is_suppressed(candidate.raw) else "ok"
        if status != previous:
            citation.source_status = status
            kind = "suppressed" if status == "suppressed" else "restored"
            db.add(CitationEvent(citation_id=citation.id, kind=kind, source_system="alma"))
            if kind == "restored":
                report.restored += 1
            else:
                report.flagged += 1
        elif not changes:
            report.unchanged += 1
        citation.source_synced_at = now

    await db.flush()
    logger.info("Catalogue sync for org %s: %s", organization_id, report)
    return report
