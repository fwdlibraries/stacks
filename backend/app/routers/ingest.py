"""Look up citations by identifier and add them bound to their source record."""
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_extension_user
from app.ingest import pipeline
from app.ingest.candidate import Candidate, SourceError
from app.ingest.fields import UnusableRecord, citation_fields
from app.ingest.resolvers import BY_SYSTEM, ResolveContext, primo
from app.ingest.sources import context_for
from app.models.models import Citation, User
from app.schemas.ingest import (
    CandidateOut,
    CitationFromSource,
    IdentifierOut,
    IngestCapabilities,
    LookupRequest,
    LookupResponse,
    SearchRequest,
    SearchResponse,
)
from app.schemas.lists import StaffCitation
from app.services import lists_service as svc
from app.services.access import load_grants
from app.services.credentials import CredentialError

logger = logging.getLogger(__name__)
router = APIRouter()


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Outbound client for source lookups (overridden in tests)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


async def resolve_context(
    current_user: User = Depends(get_extension_user),
    db: AsyncSession = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http_client),
) -> ResolveContext:
    # Lookups spend the organization's library API quota: only for people who edit lists
    if not (await load_grants(db, current_user)).anywhere("lists.edit"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to add citations")
    try:
        return await context_for(db, current_user.organization_id, http)
    except CredentialError:
        # Lookups still work through open sources; admins see the reason in the log
        logger.exception("Library source credentials for org %s can't be decrypted", current_user.organization_id)
        return ResolveContext(http=http)


def _candidate_out(candidate: Candidate) -> CandidateOut:
    return CandidateOut.from_candidate(candidate)


def _fields_or_422(candidate: Candidate) -> dict:
    try:
        return citation_fields(candidate)
    except UnusableRecord as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


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


@router.get("/ingest/capabilities", response_model=IngestCapabilities, summary="What citation sources are set up")
async def capabilities(ctx: ResolveContext = Depends(resolve_context)):
    return IngestCapabilities(library_search=primo.available(ctx))


@router.post("/ingest/search", response_model=SearchResponse, summary="Search the library's discovery system")
async def search(body: SearchRequest, ctx: ResolveContext = Depends(resolve_context)):
    """Keyword search of the organization's Primo scope.

    Catalogue results are `alma` candidates (added bound to the Alma record);
    Central Discovery Index results, mostly articles, are `primo` candidates.
    """
    if not primo.available(ctx):
        raise HTTPException(status.HTTP_409_CONFLICT, "Library search isn't set up for your organization")
    try:
        total, candidates = await pipeline.search(ctx=ctx, text=body.query, offset=body.offset, limit=body.limit)
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{exc}. Try again, or look the item up by identifier.") from exc
    return SearchResponse(total=total, offset=body.offset, candidates=[_candidate_out(c) for c in candidates])


@router.post(
    "/sections/{section_id}/citations/from-source",
    response_model=StaffCitation,
    status_code=status.HTTP_201_CREATED,
    summary="Add a citation from a source record",
)
async def create_from_source(
    section_id: uuid.UUID,
    body: CitationFromSource,
    current_user: User = Depends(get_extension_user),
    db: AsyncSession = Depends(get_db),
    ctx: ResolveContext = Depends(resolve_context),
):
    """Fetch the record named by the binding and add it at the end of the section.

    Citations from the library's system (Alma) stay bound to their record: their
    bibliographic fields are read-only and kept in sync.
    """
    section = await svc.get_section(db, current_user, section_id, need="lists.edit")
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
        **_fields_or_422(candidate),
    )
    db.add(citation)
    await svc.touch_list(db, section.reading_list_id)
    await db.flush()
    await db.refresh(citation)
    return citation
