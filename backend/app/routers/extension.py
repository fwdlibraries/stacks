"""Browser extension: connection tokens, add-to targets, and page matching."""
import dataclasses
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import any_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, get_extension_user
from app.ingest import matching
from app.ingest.page import to_entry
from app.ingest.resolvers import ResolveContext
from app.models.models import ApiKey, CourseTemplate, Organization, ReadingList, User
from app.routers.ingest import resolve_context
from app.schemas.ingest import CandidateCitation, CandidateOut
from app.services import api_tokens
from app.services import lists_service as svc

router = APIRouter()


# ── Connection tokens (session-only: the extension can't mint or list them) ─


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    browser: str = Field(default="Browser", min_length=1, max_length=40)


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = None


class TokenCreated(TokenOut):
    token: str  # shown once


@router.post("/extension/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED,
             summary="Connect a browser extension")
async def create_token(
    body: TokenCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A token that only works for the extension's endpoints. Store it in the extension;
    it can't be shown again."""
    key, token = await api_tokens.create(
        db, current_user, f"Browser extension ({body.browser})", [api_tokens.EXTENSION_SCOPE]
    )
    await db.refresh(key)
    return TokenCreated(**TokenOut.model_validate(key).model_dump(), token=token)


@router.get("/extension/tokens", response_model=list[TokenOut], summary="Connected browser extensions")
async def list_tokens(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return list(
        await db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == current_user.id, ApiKey.revoked_at.is_(None),
                   any_(ApiKey.scopes) == api_tokens.EXTENSION_SCOPE)
            .order_by(ApiKey.created_at.desc())
        )
    )


@router.delete("/extension/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect")
async def revoke_token(
    token_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    key = await db.get(ApiKey, token_id)
    if key is None or key.user_id != current_user.id or key.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    key.revoked_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── What the extension shows ─────────────────────────────────────────────────


class Me(BaseModel):
    display_name: str
    organization: str


@router.get("/extension/me", response_model=Me, summary="Who the extension is connected as")
async def me(current_user: User = Depends(get_extension_user), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, current_user.organization_id)
    return Me(display_name=current_user.display_name, organization=org.name if org else "")


class TargetSection(BaseModel):
    id: uuid.UUID
    title: str


class TargetList(BaseModel):
    id: uuid.UUID
    title: str
    course_code: str | None = None
    is_published: bool
    sections: list[TargetSection]


@router.get("/extension/targets", response_model=list[TargetList], summary="Lists and sections to add to")
async def targets(current_user: User = Depends(get_extension_user), db: AsyncSession = Depends(get_db)):
    """The organization's reading lists with their sections, most recently edited first."""
    lists = await db.scalars(
        svc.org_lists_query(current_user)
        .options(selectinload(ReadingList.sections), selectinload(ReadingList.course_template))
        .order_by(ReadingList.updated_at.desc())
        .limit(100)
    )
    return [
        TargetList(
            id=rl.id,
            title=rl.title,
            course_code=rl.course_template.code if isinstance(rl.course_template, CourseTemplate) else None,
            is_published=rl.is_published,
            sections=[TargetSection(id=s.id, title=s.title) for s in sorted(rl.sections, key=lambda s: s.sort_order)],
        )
        for rl in lists
    ]


class PageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4000)
    title: str | None = Field(default=None, max_length=2000)
    # <meta name|property> → contents, as the page has them
    meta: dict[str, list[str]] = Field(default_factory=dict, max_length=300)
    jsonld: list = Field(default_factory=list, max_length=20)


class PageOut(BaseModel):
    # The page itself, as a citation (what "as entered" adds)
    page: CandidateCitation
    candidates: list[CandidateOut]
    warnings: list[str]
    good_match: float = matching.GOOD_MATCH


SCHOLARLY = {"journal_article", "book", "ebook", "book_chapter"}


@router.post("/ingest/page", response_model=PageOut, summary="Match a web page to library records")
async def match_page(
    body: PageIn,
    current_user: User = Depends(get_extension_user),
    ctx: ResolveContext = Depends(resolve_context),
):
    """Turn a page's metadata into a citation and look for it in the library.

    Ordinary web pages (no DOI/ISBN, not an article or book) aren't searched for:
    they're added as websites.
    """
    meta = {k[:100]: [v[:2000] for v in vals[:20]] for k, vals in body.meta.items()}
    entry = to_entry(body.url, body.title, meta, body.jsonld)
    candidates, warnings = [], []
    if entry.draft.doi or entry.draft.isbn or entry.draft.resource_type in SCHOLARLY:
        candidates, warnings = await matching.match(entry, ctx)
    draft = {k: v for k, v in dataclasses.asdict(entry.draft).items() if k in CandidateCitation.model_fields}
    return PageOut(
        page=CandidateCitation.model_validate({k: v for k, v in draft.items() if v is not None}),
        candidates=[CandidateOut.from_candidate(c) for c in candidates],
        warnings=warnings,
    )
