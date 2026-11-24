"""Click-through links (/go) and their stats.

Student links point here; each click runs the organization's resolver stack
(app/services/resolution.py) and redirects straight to the resource. Clicks on
published lists are counted anonymously for instructors.
"""
import logging
import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import (
    Citation,
    College,
    CourseTemplate,
    Department,
    LinkClick,
    ListSection,
    ReadingList,
    User,
)
from app.routers.ingest import get_http_client
from app.services import lists_service as svc
from app.services import resolution
from app.services.ephemeral import EphemeralStore, get_ephemeral_store

logger = logging.getLogger(__name__)
router = APIRouter()

# Link previews, crawlers and prefetchers shouldn't count as students reading
_NOT_A_READER = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|skypeuripreview|teams|whatsapp|curl|wget|python",
    re.IGNORECASE,
)


async def _citation_with_list(db: AsyncSession, citation_id: uuid.UUID):
    return (
        await db.execute(
            select(Citation, ReadingList, College.organization_id)
            .join(Citation.section)
            .join(ListSection.reading_list)
            .join(ReadingList.course_template)
            .join(CourseTemplate.department)
            .join(Department.college)
            .where(Citation.id == citation_id)
        )
    ).first()


@router.get("/go/{citation_id}", summary="Follow a citation link", response_class=RedirectResponse)
async def go(
    citation_id: uuid.UUID,
    request: Request,
    preview: bool = False,
    db: AsyncSession = Depends(get_db),
    store: EphemeralStore = Depends(get_ephemeral_store),
    http: httpx.AsyncClient = Depends(get_http_client),
):
    """Redirect to the best current link for a citation.

    Citation IDs are unguessable and the target is only where the citation
    already points, so this needs no sign-in (students arrive from the LMS or
    a public list). `preview=true` (the editor) isn't counted.
    """
    row = await _citation_with_list(db, citation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Citation not found")
    citation, reading_list, organization_id = row

    ctx = await resolution.load_context(db, organization_id)
    key = resolution.cache_key(citation, ctx)
    cached = await store.get(key) if ctx.config.cache_ttl_seconds else None
    if cached:
        found = resolution.Resolution(**cached)
    else:
        found = await resolution.resolve(citation, ctx, http)
        # Fallback answers aren't cached: they're cheap, and a step may recover
        if found and found.step != "fallback" and ctx.config.cache_ttl_seconds:
            await store.put(key, asdict(found), ctx.config.cache_ttl_seconds)

    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No link is available for this citation")

    if not preview and reading_list.is_published and not _NOT_A_READER.search(request.headers.get("user-agent", "")):
        db.add(LinkClick(citation_id=citation.id, reading_list_id=reading_list.id, resolved_by=found.step))

    # no-store: the next click must come back here, to resolve and count it
    return RedirectResponse(found.url, status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"})


class StepOut(BaseModel):
    step: str
    outcome: str
    detail: str | None = None
    url: str | None = None


class LinkCheck(BaseModel):
    url: str | None
    resolved_by: str | None
    detail: str | None
    retracted: bool
    steps: list[StepOut]


@router.get("/citations/{citation_id}/link-check", response_model=LinkCheck, summary="Where a citation's link goes")
async def link_check(
    citation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http_client),
):
    """Run the resolver stack now (no cache) and report every step, for the editor."""
    citation = await svc.get_citation(db, current_user, citation_id)
    ctx = await resolution.load_context(db, current_user.organization_id)
    trace = resolution.Trace()
    found = await resolution.resolve(citation, ctx, http, trace)
    return LinkCheck(
        url=found.url if found else None,
        resolved_by=found.step if found else None,
        detail=found.detail if found else None,
        retracted=bool(found and found.retracted),
        steps=[StepOut(**asdict(s)) for s in trace.steps],
    )


class CitationClicks(BaseModel):
    total: int
    last_30_days: int


class ListClicks(BaseModel):
    citations: dict[uuid.UUID, CitationClicks]


@router.get("/lists/{list_id}/clicks", response_model=ListClicks, summary="Click-through counts per citation")
async def list_clicks(
    list_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reading_list = await svc.get_list(db, current_user, list_id)
    since = datetime.now(UTC) - timedelta(days=30)
    rows = await db.execute(
        select(
            LinkClick.citation_id,
            func.count(),
            func.count().filter(LinkClick.clicked_at >= since),
        )
        .where(LinkClick.reading_list_id == reading_list.id)
        .group_by(LinkClick.citation_id)
    )
    return ListClicks(
        citations={cid: CitationClicks(total=total, last_30_days=recent) for cid, total, recent in rows}
    )
