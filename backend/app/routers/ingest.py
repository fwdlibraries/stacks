"""Look up citations by identifier and add them bound to their source record."""
import dataclasses
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.ingest import pipeline
from app.ingest.candidate import Candidate, SourceError
from app.ingest.resolvers import BY_SYSTEM, ResolveContext
from app.ingest.sources import load_sources
from app.models.models import Citation, ResourceType, User
from app.schemas.ingest import (
    CandidateCitation,
    CandidateOut,
    CitationFromSource,
    IdentifierOut,
    LookupRequest,
    LookupResponse,
)
from app.schemas.lists import StaffCitation
from app.services import lists_service as svc
from app.services.credentials import CredentialError

logger = logging.getLogger(__name__)
router = APIRouter()


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Outbound client for source lookups (overridden in tests)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


async def resolve_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http_client),
) -> ResolveContext:
    try:
        sources = await load_sources(db, current_user.organization_id)
    except CredentialError:
        # Lookups still work through open sources; admins see the reason in the log
        logger.exception("Library source credentials for org %s can't be decrypted", current_user.organization_id)
        sources = {}
    return ResolveContext(http=http, sources=sources)


def _candidate_out(candidate: Candidate) -> CandidateOut:
    draft = {k: v for k, v in dataclasses.asdict(candidate.draft).items() if k in CandidateCitation.model_fields}
    return CandidateOut(
        source_system=candidate.source_system,
        source_identifier=candidate.source_identifier,
        match_method=candidate.match_method,
        confidence=candidate.confidence,
        authoritative=candidate.authoritative,
        citation=CandidateCitation.model_validate({k: v for k, v in draft.items() if v is not None}),
    )


def citation_fields(candidate: Candidate) -> dict:
    """Bibliographic Citation columns from a candidate, made safe to store and show."""
    draft = candidate.draft
    if not draft.title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That record has no title, so it can't be added")
    url = draft.url if draft.url and urlsplit(draft.url).scheme.lower() in ("http", "https") else None
    rtype = draft.resource_type if draft.resource_type in ResourceType.__members__ else "other"
    year = draft.year if draft.year and 1000 <= draft.year <= 2100 else None
    return {
        "resource_type": ResourceType(rtype),
        "title": draft.title,
        "author": draft.author or None,
        "editor": draft.editor or None,
        "year": year,
        "publisher": draft.publisher,
        "place_of_publication": draft.place_of_publication,
        "edition": draft.edition,
        "volume": draft.volume,
        "issue": draft.issue,
        "pages": draft.pages,
        "isbn": draft.isbn,
        "issn": draft.issn,
        "doi": draft.doi,
        "url": url,
        "metadata_": draft.metadata or {},
    }


@router.post("/ingest/lookup", response_model=LookupResponse, summary="Look up a citation by identifier")
async def lookup(body: LookupRequest, ctx: ResolveContext = Depends(resolve_context)):
    """Find candidates for the DOIs, ISBNs and Alma MMS IDs in `query`.

    Records from the library's own system come first; open sources (Crossref,
    Open Library) fill in when the library doesn't hold the item.
    """
    result = await pipeline.lookup(body.query, ctx)
    return LookupResponse(
        identifiers=[IdentifierOut(kind=i.kind, value=i.value) for i in result.identifiers],
        candidates=[_candidate_out(c) for c in result.candidates],
        warnings=result.warnings,
    )


@router.post(
    "/sections/{section_id}/citations/from-source",
    response_model=StaffCitation,
    status_code=status.HTTP_201_CREATED,
    summary="Add a citation from a source record",
)
async def create_from_source(
    section_id: uuid.UUID,
    body: CitationFromSource,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    ctx: ResolveContext = Depends(resolve_context),
):
    """Fetch the record named by the binding and add it at the end of the section.

    Citations from the library's system (Alma) stay bound to their record: their
    bibliographic fields are read-only and kept in sync.
    """
    section = await svc.get_section(db, current_user, section_id)
    if body.source_system not in BY_SYSTEM:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown source: {body.source_system}")
    try:
        candidate = await pipeline.fetch(body.source_system, body.source_identifier, ctx)
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{exc}. The citation wasn't added.") from exc
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That record wasn't found in the source")

    now = datetime.now(UTC)
    citation = Citation(
        list_section_id=section.id,
        sort_order=await svc.next_sort_order(db, Citation.sort_order, Citation.list_section_id == section.id),
        is_required=body.is_required,
        student_note=body.student_note,
        staff_note=body.staff_note,
        source_system=candidate.source_system,
        source_identifier=candidate.source_identifier,
        raw_import_data=candidate.raw,
        # The list-builder chose this exact record, so the binding itself is certain
        match_method=candidate.match_method,
        match_confidence=candidate.confidence,
        source_status="ok" if candidate.authoritative else None,
        source_synced_at=now if candidate.authoritative else None,
        created_by=current_user.id,
        **citation_fields(candidate),
    )
    db.add(citation)
    await svc.touch_list(db, section.reading_list_id)
    await db.flush()
    await db.refresh(citation)
    return citation
