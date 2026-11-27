"""Administration › Rollover: an upcoming term's sections, where each one's list comes
from, and the imports that fill it (app/services/rollover.py)."""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_permission
from app.models.models import (
    CourseOffering,
    CourseTemplate,
    Primary,
    RememberedMatch,
    RolloverItem,
    Term,
    User,
)
from app.services import rollover, terms

router = APIRouter(prefix="/rollover")
manage_courses = require_permission("courses.manage")

MAX_FILE = 5_000_000  # characters; a large term's loader file is well under 1 MB

Status = Literal["needs_source", "in_review", "approved", "skipped"]


# ── Settings ─────────────────────────────────────────────────────────────────


class SettingsOut(rollover.RolloverSettings):
    section_code_pattern: str | None = None


@router.get("/settings", response_model=SettingsOut, summary="How rollover reads files")
async def get_settings(user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    current = await rollover.get_settings(db, user.organization_id)
    return SettingsOut(**current.model_dump(), section_code_pattern=await terms.section_code_pattern(db, user.organization_id))


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_code_pattern: str | None = Field(default=None, max_length=120)
    course_column: str = Field(default="SEARCH_ID1", max_length=64)
    part_of_term_column: str = Field(default="Term1", max_length=64)
    lengths: dict[str, str] = Field(default_factory=dict)


@router.put("/settings", response_model=SettingsOut, summary="Change how rollover reads files")
async def put_settings(body: SettingsIn, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    try:
        value = rollover.RolloverSettings.model_validate(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _first_error(exc)) from exc
    await rollover.save_settings(db, user.organization_id, value)
    return await get_settings(user, db)


class TryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_code_pattern: str = Field(max_length=120)
    code: str = Field(max_length=200)


class TryOut(BaseModel):
    matches: bool
    error: str | None = None
    course: str | None = None
    mode: str | None = None
    length: str | None = None


@router.post("/settings/try", response_model=TryOut, summary="Try a primary code pattern")
async def try_pattern(body: TryIn, user: User = Depends(manage_courses)):
    try:
        rollover.compile_primary_pattern(body.primary_code_pattern)
    except terms.PatternError as exc:
        return TryOut(matches=False, error=str(exc))
    parsed = rollover.parse_primary_code(body.primary_code_pattern, body.code)
    if parsed is None:
        return TryOut(matches=False)
    return TryOut(matches=True, course=parsed.course, mode=parsed.mode, length=parsed.length)


# ── Primaries ────────────────────────────────────────────────────────────────


class PrimaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str | None = None
    course: str
    mode: str | None = None
    length: str | None = None
    lms_org_unit_id: str | None = None
    origin: str
    has_list: bool = False


def _primary_out(primary: Primary, course_code: str) -> PrimaryOut:
    return PrimaryOut(
        id=primary.id, code=primary.code, name=primary.name, course=course_code, mode=primary.mode,
        length=primary.length, lms_org_unit_id=primary.lms_org_unit_id, origin=primary.origin,
        has_list=primary.reading_list_id is not None,
    )


@router.get("/primaries", response_model=list[PrimaryOut], summary="Known primary shells")
async def list_primaries(
    q: str | None = None, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)
):
    query = (
        select(Primary, CourseTemplate.code)
        .join(CourseTemplate, CourseTemplate.id == Primary.course_template_id)
        .where(Primary.organization_id == user.organization_id)
        .order_by(Primary.code)
        .limit(500)
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(Primary.code.ilike(like), Primary.name.ilike(like)))
    return [_primary_out(p, code) for p, code in await db.execute(query)]


class FileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_FILE)


class SkippedOut(BaseModel):
    line: int
    code: str
    reason: str


class PrimariesImportOut(BaseModel):
    added: int
    updated: int
    skipped: list[SkippedOut]


@router.post("/primaries/import", response_model=PrimariesImportOut, summary="Import a list of primary shells")
async def import_primaries(body: FileIn, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    try:
        result = await rollover.import_primaries(db, user.organization_id, body.text)
    except rollover.FileProblem as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return PrimariesImportOut(added=result.added, updated=result.updated,
                              skipped=[SkippedOut(**s.__dict__) for s in result.skipped])


class PrimaryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=300)


@router.post("/primaries", response_model=PrimaryOut, status_code=status.HTTP_201_CREATED, summary="Add a primary")
async def add_primary(body: PrimaryIn, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    settings = await rollover.get_settings(db, user.organization_id)
    parsed = rollover.parse_primary_code(settings.primary_code_pattern, body.code)
    if parsed is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That isn't a primary code" if settings.primary_code_pattern else "Set how primary shells are coded first",
        )
    primary, created = await rollover.add_primary(db, user.organization_id, parsed, origin="manual", name=body.name)
    if not created:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{primary.code} is already a primary")
    return _primary_out(primary, (await db.get(CourseTemplate, primary.course_template_id)).code)


@router.delete("/primaries/{primary_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a primary")
async def delete_primary(primary_id: uuid.UUID, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    """Sections matched to it go back to the rules (or the queue)."""
    primary = await _own_primary(db, user, primary_id)
    affected = (await db.scalars(select(RolloverItem).where(RolloverItem.primary_id == primary.id))).all()
    await db.delete(primary)
    await db.flush()
    settings = await rollover.get_settings(db, user.organization_id)
    for item in affected:
        await db.refresh(item)
        if item.match_source and item.primary_id is None:
            item.match_source = None
            if item.status not in rollover.OPEN:
                item.status = "needs_source"
        await rollover.match(db, user.organization_id, item, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── A term's sections ────────────────────────────────────────────────────────


class ItemOut(BaseModel):
    id: uuid.UUID
    section: str | None
    lms_code: str | None
    course: str
    course_name: str
    department: str | None
    instructors: list[str]
    part_of_term: str | None
    length: str | None
    mode: str | None
    primary: PrimaryOut | None
    match_source: str | None
    file_primary_code: str | None
    status: str
    problems: list[str]
    notes: str | None
    decided_at: datetime | None


class ItemsOut(BaseModel):
    term: dict
    items: list[ItemOut]
    total: int
    counts: dict[str, int]  # by status, across the term
    problems: int  # items with problems, across the term


async def _own_term(db: AsyncSession, user: User, term_id: uuid.UUID) -> Term:
    term = await db.scalar(select(Term).where(Term.id == term_id, Term.organization_id == user.organization_id))
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")
    return term


async def _own_primary(db: AsyncSession, user: User, primary_id: uuid.UUID) -> Primary:
    primary = await db.scalar(
        select(Primary).where(Primary.id == primary_id, Primary.organization_id == user.organization_id)
    )
    if primary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Primary not found")
    return primary


async def _own_item(db: AsyncSession, user: User, item_id: uuid.UUID) -> RolloverItem:
    item = await db.scalar(
        select(RolloverItem)
        .join(Term, Term.id == RolloverItem.term_id)
        .where(RolloverItem.id == item_id, Term.organization_id == user.organization_id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    return item


async def _items_out(db: AsyncSession, rows) -> list[ItemOut]:
    primary_ids = {item.primary_id for item, *_ in rows if item.primary_id}
    primaries = {}
    if primary_ids:
        for p, code in await db.execute(
            select(Primary, CourseTemplate.code)
            .join(CourseTemplate, CourseTemplate.id == Primary.course_template_id)
            .where(Primary.id.in_(primary_ids))
        ):
            primaries[p.id] = _primary_out(p, code)
    return [
        ItemOut(
            id=item.id, section=offering.section, lms_code=offering.lms_code, course=course.code,
            course_name=course.name, department=item.department, instructors=item.instructors or [],
            part_of_term=item.part_of_term, length=item.length, mode=item.mode,
            primary=primaries.get(item.primary_id), match_source=item.match_source,
            file_primary_code=item.file_primary_code, status=item.status, problems=item.problems or [],
            notes=item.notes, decided_at=item.decided_at,
        )
        for item, offering, course in rows
    ]


def _base(term: Term):
    return (
        select(RolloverItem, CourseOffering, CourseTemplate)
        .join(CourseOffering, CourseOffering.id == RolloverItem.course_offering_id)
        .join(CourseTemplate, CourseTemplate.id == CourseOffering.course_template_id)
        .where(RolloverItem.term_id == term.id)
    )


@router.get("/terms/{term_id}/items", response_model=ItemsOut, summary="A term's sections in rollover")
async def list_items(
    term_id: uuid.UUID,
    status_: Status | None = Query(default=None, alias="status"),
    has_problems: bool = False,
    q: str | None = None,
    offset: int = 0,
    limit: int = 200,
    user: User = Depends(manage_courses),
    db: AsyncSession = Depends(get_db),
):
    term = await _own_term(db, user, term_id)
    query = _base(term)
    if status_:
        query = query.where(RolloverItem.status == status_)
    if has_problems:
        query = query.where(func.jsonb_array_length(RolloverItem.problems) > 0)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(
            CourseOffering.lms_code.ilike(like), CourseOffering.section.ilike(like), CourseTemplate.code.ilike(like),
            CourseTemplate.name.ilike(like), RolloverItem.department.ilike(like),
        ))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(query.order_by(CourseTemplate.code, CourseOffering.lms_code)
                         .offset(max(offset, 0)).limit(min(max(limit, 1), 500)))
    ).all()
    counts = dict((await db.execute(
        select(RolloverItem.status, func.count()).where(RolloverItem.term_id == term.id).group_by(RolloverItem.status)
    )).all())
    problems = await db.scalar(
        select(func.count()).select_from(RolloverItem)
        .where(RolloverItem.term_id == term.id, func.jsonb_array_length(RolloverItem.problems) > 0)
    )
    return ItemsOut(
        term={"id": term.id, "code": term.code, "name": term.name}, items=await _items_out(db, rows), total=total,
        counts={s: counts.get(s, 0) for s in rollover.STATUSES}, problems=problems,
    )


class SectionsImportOut(BaseModel):
    added: int
    updated: int
    skipped: list[SkippedOut]
    matched: dict[str, int]
    needs_source: int


@router.post("/terms/{term_id}/import", response_model=SectionsImportOut, summary="Import a course loader file")
async def import_sections(
    term_id: uuid.UUID, body: FileIn, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)
):
    term = await _own_term(db, user, term_id)
    try:
        result = await rollover.import_loader(db, user.organization_id, term, body.text)
    except rollover.FileProblem as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return SectionsImportOut(
        added=result.added, updated=result.updated, skipped=[SkippedOut(**s.__dict__) for s in result.skipped],
        matched=result.matched, needs_source=result.needs_source,
    )


@router.post("/terms/{term_id}/rematch", status_code=status.HTTP_204_NO_CONTENT, summary="Match sections again")
async def rematch(term_id: uuid.UUID, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    """After adding primaries or changing settings. Approved, skipped and manual choices stay."""
    await rollover.rematch_term(db, user.organization_id, await _own_term(db, user, term_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Set to choose a primary; null to clear a choice and let the rules decide
    primary_id: uuid.UUID | None = None
    set_primary: bool = False
    remember: bool = True  # use this choice for the course variant in later terms
    status: Status | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/items/{item_id}", response_model=ItemOut, summary="Change a section in rollover")
async def update_item(
    item_id: uuid.UUID, body: ItemIn, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)
):
    item = await _own_item(db, user, item_id)
    if body.set_primary:
        primary = await _own_primary(db, user, body.primary_id) if body.primary_id else None
        await rollover.choose(db, user.organization_id, item, primary, user, remember=body.remember)
    if body.status:
        try:
            rollover.set_status(item, body.status, user)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if "notes" in body.model_fields_set:
        item.notes = (body.notes or "").strip() or None
    await db.flush()
    await db.refresh(item)
    rows = (await db.execute(_base(await db.get(Term, item.term_id)).where(RolloverItem.id == item.id))).all()
    return (await _items_out(db, rows))[0]


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    status: Status


class BulkOut(BaseModel):
    changed: int
    refused: int  # e.g. approving a section with no primary


@router.post("/items/bulk", response_model=BulkOut, summary="Change several sections' status")
async def bulk_status(body: BulkIn, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    items = (await db.scalars(
        select(RolloverItem)
        .join(Term, Term.id == RolloverItem.term_id)
        .where(RolloverItem.id.in_(body.ids), Term.organization_id == user.organization_id)
    )).all()
    changed = refused = 0
    for item in items:
        try:
            rollover.set_status(item, body.status, user)
            changed += 1
        except ValueError:
            refused += 1
    await db.flush()
    return BulkOut(changed=changed, refused=refused)


# ── Remembered matches ───────────────────────────────────────────────────────


class RememberedOut(BaseModel):
    id: uuid.UUID
    course: str
    length: str
    mode: str
    primary: str
    created_at: datetime | None


@router.get("/remembered", response_model=list[RememberedOut], summary="Remembered choices of primary")
async def list_remembered(user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(RememberedMatch, CourseTemplate.code, Primary.code)
        .join(CourseTemplate, CourseTemplate.id == RememberedMatch.course_template_id)
        .join(Primary, Primary.id == RememberedMatch.primary_id)
        .where(RememberedMatch.organization_id == user.organization_id)
        .order_by(CourseTemplate.code, RememberedMatch.length)
    )
    return [
        RememberedOut(id=r.id, course=course, length=r.length, mode=r.mode, primary=primary, created_at=r.created_at)
        for r, course, primary in rows
    ]


@router.delete("/remembered/{remembered_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Forget a choice")
async def forget(remembered_id: uuid.UUID, user: User = Depends(manage_courses), db: AsyncSession = Depends(get_db)):
    found = await db.scalar(select(RememberedMatch).where(
        RememberedMatch.id == remembered_id, RememberedMatch.organization_id == user.organization_id
    ))
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(found)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _first_error(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return errors()[0].get("msg", str(exc)).removeprefix("Value error, ")
    return str(exc)
