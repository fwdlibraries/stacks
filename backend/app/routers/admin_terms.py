"""Administration › Terms: the organization's teaching terms, and how its LMS course
shells are coded so launches find their term (app/services/terms.py)."""
import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_permission
from app.models.models import CourseOffering, Organization, Term, User
from app.services import tenancy, terms

router = APIRouter()
manage_settings = require_permission("settings.manage")

_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class TermIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    starts_on: date | None = None
    ends_on: date | None = None
    rollover_on: date | None = None
    lists_due_on: date | None = None

    @field_validator("code", mode="before")
    @classmethod
    def _code(cls, value):
        value = str(value or "").strip().lower()
        if not _CODE.match(value):
            raise ValueError("Use letters, numbers and dashes, e.g. 202710 or fall-2027")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value):
        return str(value or "").strip()

    @model_validator(mode="after")
    def _dates(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("The term can't end before it starts")
        return self


class TermAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    starts_on: date | None = None
    ends_on: date | None = None
    rollover_on: date | None = None
    lists_due_on: date | None = None
    offerings: int = 0


class TermsOut(BaseModel):
    terms: list[TermAdminOut]
    section_code_pattern: str | None = None


class PatternIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_code_pattern: str | None = Field(default=None, max_length=120)


class TryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_code_pattern: str | None = Field(default=None, max_length=120)
    code: str = Field(max_length=200)


class TryOut(BaseModel):
    matches: bool
    error: str | None = None
    term: str | None = None
    term_name: str | None = None  # the Term record's name, if that term exists
    crn: str | None = None
    section: str | None = None
    course: str | None = None


async def _terms_out(db: AsyncSession, user: User) -> TermsOut:
    counts = (
        select(CourseOffering.term_id, func.count().label("n")).group_by(CourseOffering.term_id).subquery()
    )
    rows = await db.execute(
        select(Term, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.term_id == Term.id)
        .where(Term.organization_id == user.organization_id)
        .order_by(Term.starts_on.desc().nulls_last(), Term.code.desc())
    )
    out = []
    for term, n in rows:
        item = TermAdminOut.model_validate(term)
        item.offerings = n
        out.append(item)
    return TermsOut(terms=out, section_code_pattern=await terms.section_code_pattern(db, user.organization_id))


async def _own_term(db: AsyncSession, user: User, term_id: uuid.UUID) -> Term:
    term = await db.scalar(select(Term).where(Term.id == term_id, Term.organization_id == user.organization_id))
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")
    return term


async def _code_taken(db: AsyncSession, user: User, code: str, except_id: uuid.UUID | None = None) -> bool:
    query = select(Term.id).where(Term.organization_id == user.organization_id, Term.code == code)
    if except_id:
        query = query.where(Term.id != except_id)
    return (await db.scalar(query.limit(1))) is not None


@router.get("/terms", response_model=TermsOut, summary="Terms and LMS section codes")
async def get_terms(user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    return await _terms_out(db, user)


@router.post("/terms", response_model=TermsOut, status_code=status.HTTP_201_CREATED, summary="Add a term")
async def add_term(body: TermIn, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    if await _code_taken(db, user, body.code):
        raise HTTPException(status.HTTP_409_CONFLICT, f"There's already a term with the code {body.code}")
    db.add(Term(organization_id=user.organization_id, **body.model_dump()))
    await db.flush()
    return await _terms_out(db, user)


@router.put("/terms/{term_id}", response_model=TermsOut, summary="Change a term")
async def update_term(
    term_id: uuid.UUID, body: TermIn, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)
):
    """The code can't change once courses use the term: it's part of student links."""
    term = await _own_term(db, user, term_id)
    if body.code != term.code:
        if await terms.offerings_count(db, term.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Courses already use this term's code, so it can't change (it's in student links)"
            )
        if await _code_taken(db, user, body.code, except_id=term.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"There's already a term with the code {body.code}")
    for field, value in body.model_dump().items():
        setattr(term, field, value)
    await db.flush()
    return await _terms_out(db, user)


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a term")
async def delete_term(term_id: uuid.UUID, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    term = await _own_term(db, user, term_id)
    if await terms.offerings_count(db, term.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Courses use this term, so it can't be removed")
    await db.delete(term)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/terms-pattern", response_model=TermsOut, summary="Set how LMS course shells are coded")
async def save_pattern(body: PatternIn, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, user.organization_id)
    current = dict(org.settings or {})
    current["section_code_pattern"] = body.section_code_pattern
    try:
        validated = tenancy.OrgSettings.model_validate(current)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _first_error(exc)) from exc
    org.settings = {**(org.settings or {}), "section_code_pattern": validated.section_code_pattern}
    await db.flush()
    return await _terms_out(db, user)


@router.post("/terms-pattern/try", response_model=TryOut, summary="Try a section code pattern")
async def try_pattern(body: TryIn, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    """How a pattern (unsaved, or the saved one if none is given) reads an LMS course code."""
    pattern = body.section_code_pattern or await terms.section_code_pattern(db, user.organization_id)
    if not pattern:
        return TryOut(matches=False, error="Enter a pattern first")
    try:
        terms.compile_pattern(pattern)
    except terms.PatternError as exc:
        return TryOut(matches=False, error=str(exc))
    parsed = terms.parse_section_code(pattern, body.code)
    if parsed is None:
        return TryOut(matches=False)
    name = await db.scalar(
        select(Term.name).where(Term.organization_id == user.organization_id, Term.code == parsed.term)
    )
    return TryOut(matches=True, term=parsed.term, term_name=name, crn=parsed.crn, section=parsed.section, course=parsed.course)


def _first_error(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        message = errors()[0].get("msg", str(exc))
        return message.removeprefix("Value error, ")
    return str(exc)
