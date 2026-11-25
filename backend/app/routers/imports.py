"""Bulk import: paste or upload a bibliography, review matches, add to a section."""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.ingest import bulk
from app.ingest.parsers import ParseError
from app.ingest.resolvers import ResolveContext
from app.models.models import BackgroundJob, ImportItem, User
from app.routers.ingest import resolve_context
from app.schemas.ingest import CandidateOut
from app.services import lists_service as svc

router = APIRouter()

MAX_TEXT = 1_000_000  # characters; ~300 entries is far below this


def enqueue_matching(job_id: str) -> None:
    """Hand matching to the worker (replaced in tests)."""
    from app.tasks.import_tasks import match_bulk_import

    match_bulk_import.delay(job_id)


class ImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    format: Literal["auto", "ris", "bibtex", "text"] = "auto"
    section_id: uuid.UUID


class ImportEntry(BaseModel):
    title: str | None = None
    author: list[str] = []
    year: int | None = None
    resource_type: str | None = None
    doi: str | None = None
    isbn: str | None = None


class ImportItemOut(BaseModel):
    id: uuid.UUID
    status: str
    text: str
    structured: bool
    entry: ImportEntry
    candidates: list[CandidateOut]
    confidence: float | None
    warnings: list[str]
    resulting_citation_id: uuid.UUID | None = None


class ImportJobOut(BaseModel):
    id: uuid.UUID
    status: str  # queued | processing | awaiting_review | completed | failed
    total: int
    matched: int
    section_id: uuid.UUID
    created_at: datetime
    error: str | None = None
    # Matches at or above this are preselected in review
    good_match: float = bulk.matching.GOOD_MATCH
    items: list[ImportItemOut] = []


def _item_out(item: ImportItem) -> ImportItemOut:
    data = item.normalized_data
    draft = data.get("draft") or {}
    return ImportItemOut(
        id=item.id,
        status=item.status,
        text=data.get("text", ""),
        structured=data.get("structured", True),
        entry=ImportEntry(**{k: draft.get(k) for k in ImportEntry.model_fields if draft.get(k) is not None}),
        candidates=[CandidateOut.model_validate(c) for c in data.get("candidates") or []],
        confidence=item.confidence_score,
        warnings=item.warnings or [],
        resulting_citation_id=item.resulting_citation_id,
    )


async def _job(db: AsyncSession, user: User, job_id: uuid.UUID) -> BackgroundJob:
    job = await db.get(BackgroundJob, job_id)
    if job is None or job.job_type != bulk.JOB_TYPE or job.payload.get("organization_id") != str(user.organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return job


async def _job_out(db: AsyncSession, job: BackgroundJob, *, with_items: bool) -> ImportJobOut:
    items = []
    if with_items:
        items = list(
            await db.scalars(
                select(ImportItem).where(ImportItem.import_job_id == job.id).order_by(ImportItem.sort_order)
            )
        )
    result = job.result or {}
    return ImportJobOut(
        id=job.id,
        status=job.status,
        total=result.get("total", 0),
        matched=result.get("matched", 0),
        section_id=uuid.UUID(job.payload["section_id"]),
        created_at=job.created_at,
        error=job.error,
        items=[_item_out(i) for i in items],
    )


@router.post(
    "/lists/{list_id}/imports",
    response_model=ImportJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a bulk import",
)
async def start_import(
    list_id: uuid.UUID,
    body: ImportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse RIS, BibTeX or a pasted bibliography now; match entries in the background.

    Poll GET /imports/{id} until `status` is `awaiting_review`.
    """
    reading_list = await svc.get_list(db, current_user, list_id)
    section = await svc.get_section(db, current_user, body.section_id)
    if section.reading_list_id != reading_list.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That section isn't in this reading list")
    try:
        job = await bulk.create_job(db, current_user, section, body.text, body.format)
    except ParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if (job.result or {}).get("total", 0) == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No references found in that text")
    await db.commit()  # the worker must see the job
    enqueue_matching(str(job.id))
    return await _job_out(db, job, with_items=False)


@router.get("/imports/{job_id}", response_model=ImportJobOut, summary="Bulk import status and matches")
async def get_import(
    job_id: uuid.UUID,
    items: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, current_user, job_id)
    return await _job_out(db, job, with_items=items)


class ItemChoice(BaseModel):
    id: uuid.UUID
    choice: Literal["match", "as_entered", "skip"]
    candidate_index: int | None = Field(default=None, ge=0, le=10)


class AddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ItemChoice] = Field(max_length=300)


class AddResponse(BaseModel):
    added: int
    skipped: int
    failed: list[dict]


@router.post("/imports/{job_id}/add", response_model=AddResponse, summary="Add reviewed entries as citations")
async def add_import(
    job_id: uuid.UUID,
    body: AddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    ctx: ResolveContext = Depends(resolve_context),
):
    """Create citations for the chosen entries, in order, at the end of the import's
    section. Entries not listed are skipped. Each import can be added once."""
    job = await _job(db, current_user, job_id)
    if job.status != "awaiting_review":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This import can't be added now (it's {job.status.replace('_', ' ')})")
    section = await svc.get_section(db, current_user, uuid.UUID(job.payload["section_id"]))
    choices = {c.id: (c.choice, c.candidate_index) for c in body.items}
    report = await bulk.add_items(db, current_user, job, section, choices, ctx)
    return AddResponse(added=report.added, skipped=report.skipped, failed=report.failed)
