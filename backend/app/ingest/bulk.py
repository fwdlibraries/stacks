"""Bulk import jobs: parse → match (background) → review → add.

A job is a BackgroundJob (job_type 'bulk_import') with one ImportItem per entry.
Items hold the entry as parsed plus up to five scored candidates; the review
screen picks one, "as entered", or skip for each, and `add_items` creates the
citations in one go.
"""
import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest import matching
from app.ingest.candidate import AUTHORITATIVE_SOURCES, Candidate, SourceError
from app.ingest.draft import CitationDraft
from app.ingest.fields import UnusableRecord, citation_fields
from app.ingest.parsers import Entry, Format, parse
from app.ingest.resolvers import ResolveContext, alma
from app.models.models import BackgroundJob, Citation, ImportItem, ListSection, User
from app.schemas.ingest import CandidateOut
from app.services import lists_service as svc

JOB_TYPE = "bulk_import"
_DRAFT_FIELDS = {f.name for f in dataclasses.fields(CitationDraft)} - {"section_title", "student_note", "staff_note"}


async def create_job(
    db: AsyncSession, user: User, section: ListSection, text: str, fmt: Format | Literal["auto"]
) -> BackgroundJob:
    entries = parse(text, fmt)
    job = BackgroundJob(
        job_type=JOB_TYPE,
        status="queued",
        payload={
            "organization_id": str(user.organization_id),
            "reading_list_id": str(section.reading_list_id),
            "section_id": str(section.id),
        },
        result={"total": len(entries), "matched": 0},
        created_by=user.id,
    )
    db.add(job)
    await db.flush()
    for i, entry in enumerate(entries):
        db.add(
            ImportItem(
                import_job_id=job.id,
                raw_data={"text": entry.text, "fields": entry.raw},
                normalized_data={
                    "draft": {k: v for k, v in dataclasses.asdict(entry.draft).items() if k in _DRAFT_FIELDS},
                    "text": entry.text,
                    "structured": entry.structured,
                    "candidates": [],
                },
                status="matching",
                target_section_id=section.id,
                sort_order=i,
            )
        )
    await db.flush()
    return job


def _entry(item: ImportItem) -> Entry:
    data = item.normalized_data
    return Entry(draft=CitationDraft(**data["draft"]), text=data["text"], structured=data["structured"])


async def run_matching(db: AsyncSession, job_id: uuid.UUID, ctx: ResolveContext) -> None:
    """Match every item, committing as it goes so the editor can show progress."""
    job = await db.get(BackgroundJob, job_id)
    if job is None or job.status not in ("queued", "processing"):
        return
    items = list(
        await db.scalars(select(ImportItem).where(ImportItem.import_job_id == job.id).order_by(ImportItem.sort_order))
    )
    job.status, job.started_at = "processing", datetime.now(UTC)
    await db.commit()

    matched = 0
    async for i, candidates, warnings in matching.match_all([_entry(item) for item in items], ctx):
        item = items[i]
        item.normalized_data = {
            **item.normalized_data,
            "candidates": [CandidateOut.from_candidate(c).model_dump() for c in candidates],
        }
        item.confidence_score = candidates[0].confidence if candidates else 0.0
        item.warnings = warnings
        item.status = "pending_review"
        matched += 1
        job.result = {"total": len(items), "matched": matched}
        await db.commit()

    job.status, job.completed_at = "awaiting_review", datetime.now(UTC)
    await db.commit()


Choice = Literal["match", "as_entered", "skip"]


@dataclasses.dataclass
class AddReport:
    added: int = 0
    skipped: int = 0
    failed: list[dict] = dataclasses.field(default_factory=list)


def _stored_candidate(item: ImportItem, index: int) -> Candidate | None:
    stored = item.normalized_data.get("candidates") or []
    if not 0 <= index < len(stored):
        return None
    c = stored[index]
    fields = {k: v for k, v in c["citation"].items() if k in _DRAFT_FIELDS}
    return Candidate(
        draft=CitationDraft(**fields),
        source_system=c["source_system"],
        source_identifier=c["source_identifier"],
        match_method=c["match_method"],
        confidence=c["confidence"],
    )


def _as_entered(item: ImportItem) -> dict:
    entry = _entry(item)
    draft = entry.draft
    if not draft.title:
        # A pasted reference that matched nothing: best-guess title, full reference kept alongside
        draft = dataclasses.replace(
            draft,
            title=(matching.guess_title(entry.text) or entry.text)[:500],
            resource_type="other",
            metadata={**draft.metadata, "original_reference": entry.text},
        )
    return citation_fields(Candidate(draft=draft, source_system="import", source_identifier="", match_method="", confidence=0))


async def add_items(
    db: AsyncSession,
    user: User,
    job: BackgroundJob,
    section: ListSection,
    choices: dict[uuid.UUID, tuple[Choice, int | None]],
    ctx: ResolveContext,
) -> AddReport:
    report = AddReport()
    items = list(
        await db.scalars(
            select(ImportItem)
            .where(ImportItem.import_job_id == job.id, ImportItem.status == "pending_review")
            .order_by(ImportItem.sort_order)
        )
    )
    chosen = {item.id: (item, *choices.get(item.id, ("skip", None))) for item in items}

    # Library records: fetch the full catalogue records in one go (search results carry
    # only the discovery summary); the nightly sync keeps them current afterwards
    alma_ids = [
        cand.source_identifier
        for item, choice, index in chosen.values()
        if choice == "match" and (cand := _stored_candidate(item, index or 0)) and cand.source_system == "alma"
    ]
    full_records: dict[str, Candidate | None] = {}
    if alma_ids and "alma" in ctx.sources:
        try:
            full_records = await alma.fetch_many(alma_ids, ctx)
        except SourceError:
            full_records = {}

    now = datetime.now(UTC)
    sort_order = await svc.next_sort_order(db, Citation.sort_order, Citation.list_section_id == section.id)
    for item, choice, index in chosen.values():
        item.reviewed_by, item.reviewed_at = user.id, now
        if choice == "skip":
            item.status = "rejected"
            report.skipped += 1
            continue
        try:
            if choice == "match":
                candidate = _stored_candidate(item, index or 0)
                if candidate is None:
                    raise UnusableRecord("That match is no longer available")
                if candidate.source_system == "alma" and (full := full_records.get(candidate.source_identifier)):
                    # Keep how it was matched; take the catalogue's full details
                    full.match_method, full.confidence = candidate.match_method, candidate.confidence
                    candidate = full
                fields = citation_fields(candidate)
                binding = {
                    "source_system": candidate.source_system,
                    "source_identifier": candidate.source_identifier,
                    "match_method": candidate.match_method,
                    "match_confidence": candidate.confidence,
                }
                bound = candidate.source_system in AUTHORITATIVE_SOURCES
                binding |= {"source_status": "ok" if bound else None, "source_synced_at": now if bound else None}
            else:
                fields = _as_entered(item)
                binding = {"source_system": "import", "match_method": "as_entered"}
        except UnusableRecord as exc:
            report.failed.append({"item_id": str(item.id), "reason": str(exc)})
            continue
        citation = Citation(
            list_section_id=section.id,
            sort_order=sort_order,
            raw_import_data=item.raw_data,
            created_by=user.id,
            **binding,
            **fields,
        )
        sort_order += 1
        db.add(citation)
        await db.flush()
        item.status, item.resulting_citation_id = "accepted", citation.id
        report.added += 1

    job.status = "completed"
    job.result = {**(job.result or {}), "added": report.added, "skipped": report.skipped, "failed": len(report.failed)}
    await svc.touch_list(db, section.reading_list_id)
    await db.flush()
    return report
