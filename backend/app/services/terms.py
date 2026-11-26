"""Terms, per-term section lists and copying lists between terms (docs/design/rollover.md).

Stage 1 of rollover:
- Terms are records (Term); offerings link to one, and keep its code as text for URLs.
- A list is a course list (shared by every term, as before terms had lists), a section
  list (one offering's), or later a primary list.
- Copying a list makes a draft section list for another term, keeping each section's
  and citation's item_key so the same reading can be followed across terms.
- An organization can say how its LMS course shells are coded ("{crn}.{term}"), so a
  launch from a live section finds its term, and its offering by exact code.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Citation,
    College,
    CourseOffering,
    CourseTemplate,
    Department,
    ListSection,
    OfferingListOverride,
    Organization,
    ReadingList,
    Term,
    User,
)
from app.services import tenancy

DEFAULT_TERM = "current"

# ── Term codes ───────────────────────────────────────────────────────────────


def slug(raw: str) -> str:
    """URL-safe term code: lower case, runs of other characters become '-'."""
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def term_name(code: str) -> str:
    """A readable default name for a term known only by its code: 'fall-2027' → 'Fall 2027'."""
    return " ".join(part.capitalize() for part in code.split("-")) if not code.isdigit() else code


# ── LMS section codes ────────────────────────────────────────────────────────

# Placeholders an organization can use in its section code pattern
FIELDS = {"term": r"[A-Za-z0-9-]+", "crn": r"[A-Za-z0-9]+", "section": r"[A-Za-z0-9]+", "course": r"[A-Za-z0-9 _-]+?"}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class PatternError(ValueError):
    pass


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """'{crn}.{term}' → a regular expression for whole LMS course codes. Text outside the
    placeholders must appear literally. The pattern must include {term}."""
    names = _PLACEHOLDER.findall(pattern)
    unknown = sorted(set(names) - set(FIELDS))
    if unknown:
        raise PatternError(f"Unknown placeholder {{{unknown[0]}}}; use {', '.join('{' + f + '}' for f in FIELDS)}")
    if "term" not in names:
        raise PatternError("The pattern needs {term}, the term code")
    if len(names) != len(set(names)):
        raise PatternError("Use each placeholder once")
    out, pos = [], 0
    for match in _PLACEHOLDER.finditer(pattern):
        out.append(re.escape(pattern[pos : match.start()]))
        out.append(f"(?P<{match.group(1)}>{FIELDS[match.group(1)]})")
        pos = match.end()
    out.append(re.escape(pattern[pos:]))
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


@dataclass
class SectionCode:
    term: str
    crn: str | None = None
    section: str | None = None
    course: str | None = None


def parse_section_code(pattern: str | None, code: str | None) -> SectionCode | None:
    """The parts of an LMS course code, if it matches the organization's pattern."""
    if not pattern or not code:
        return None
    try:
        match = compile_pattern(pattern).match(code.strip())
    except PatternError:
        return None
    if match is None:
        return None
    parts = match.groupdict()
    return SectionCode(
        term=slug(parts["term"]), crn=parts.get("crn"), section=parts.get("section"), course=parts.get("course")
    )


async def section_code_pattern(db: AsyncSession, organization_id: uuid.UUID) -> str | None:
    raw = await db.scalar(select(Organization.settings).where(Organization.id == organization_id))
    return tenancy.OrgSettings.model_validate(raw or {}).section_code_pattern


# ── Terms ────────────────────────────────────────────────────────────────────


async def find_or_create_term(
    db: AsyncSession, organization_id: uuid.UUID, code: str, name: str | None = None
) -> Term:
    term = await db.scalar(select(Term).where(Term.organization_id == organization_id, Term.code == code))
    if term is None:
        term = Term(organization_id=organization_id, code=code, name=(name or "").strip() or term_name(code))
        db.add(term)
        await db.flush()
    return term


async def organization_of_template(db: AsyncSession, template_id: uuid.UUID) -> uuid.UUID:
    return await db.scalar(
        select(College.organization_id)
        .join(Department, Department.college_id == College.id)
        .join(CourseTemplate, CourseTemplate.department_id == Department.id)
        .where(CourseTemplate.id == template_id)
    )


async def offering_for(
    db: AsyncSession, template: CourseTemplate, term: Term, section: str | None = None
) -> CourseOffering:
    """The course's offering in a term (and section), created if there isn't one."""
    query = select(CourseOffering).where(
        CourseOffering.course_template_id == template.id, CourseOffering.term == term.code
    )
    query = query.where(CourseOffering.section == section) if section else query.order_by(
        CourseOffering.section.nulls_first(), CourseOffering.created_at
    )
    offering = await db.scalar(query.limit(1))
    if offering is None:
        offering = CourseOffering(course_template_id=template.id, term=term.code, term_id=term.id, section=section)
        db.add(offering)
        await db.flush()
    elif offering.term_id is None:
        offering.term_id = term.id
    return offering


# ── Which list an offering shows ─────────────────────────────────────────────


async def offering_list(db: AsyncSession, offering: CourseOffering, *, load_sections: bool = False) -> ReadingList | None:
    """The offering's reading list:
    1. its own section list (published first, then most recently updated);
    2. an active override;
    3. the course's shared list (published first, then most recent).
    Other terms' section lists are never used."""
    options = [selectinload(ReadingList.sections).selectinload(ListSection.citations)] if load_sections else []
    order = (ReadingList.is_published.desc(), ReadingList.updated_at.desc())

    found = await db.scalar(
        select(ReadingList).where(ReadingList.course_offering_id == offering.id).order_by(*order).options(*options).limit(1)
    )
    if found is None:
        found = await db.scalar(
            select(ReadingList)
            .join(OfferingListOverride, OfferingListOverride.reading_list_id == ReadingList.id)
            .where(OfferingListOverride.course_offering_id == offering.id, OfferingListOverride.is_active.is_(True))
            .options(*options)
            .limit(1)
        )
    if found is None:
        found = await db.scalar(
            select(ReadingList)
            .where(ReadingList.course_template_id == offering.course_template_id, ReadingList.kind == "course")
            .order_by(*order)
            .options(*options)
            .limit(1)
        )
    return found


# ── Copying ──────────────────────────────────────────────────────────────────

_SKIP = {"id", "created_at", "updated_at", "created_by"}


def _columns(row, skip: set[str]) -> dict:
    """Column values of an ORM row by attribute name, minus `skip`."""
    return {
        attr.key: getattr(row, attr.key)
        for attr in inspect(type(row)).column_attrs
        if attr.key not in skip
    }


class AlreadyHasList(Exception):
    def __init__(self, existing: ReadingList):
        self.existing = existing


async def copy_list(db: AsyncSession, source_id: uuid.UUID, offering: CourseOffering, user: User | None) -> ReadingList:
    """A draft section list for `offering`, copied from the list `source_id`: same details,
    sections and citations (notes and library bindings included), same item keys."""
    existing = await db.scalar(select(ReadingList).where(ReadingList.course_offering_id == offering.id).limit(1))
    if existing is not None:
        raise AlreadyHasList(existing)
    source = await db.scalar(
        select(ReadingList)
        .where(ReadingList.id == source_id)
        .options(selectinload(ReadingList.sections).selectinload(ListSection.citations))
        .execution_options(populate_existing=True)
    )
    copy = ReadingList(
        course_template_id=offering.course_template_id,
        kind="section",
        course_offering_id=offering.id,
        copied_from_list_id=source.id,
        copied_at=datetime.now(UTC),
        title=source.title,
        description=source.description,
        visibility=source.visibility,
        is_published=False,
        created_by=user.id if user else None,
    )
    db.add(copy)
    await db.flush()
    for section in source.sections:
        new_section = ListSection(reading_list_id=copy.id, **_columns(section, _SKIP | {"reading_list_id"}))
        db.add(new_section)
        await db.flush()
        for citation in section.citations:
            db.add(
                Citation(
                    list_section_id=new_section.id,
                    created_by=user.id if user else None,
                    **_columns(citation, _SKIP | {"list_section_id"}),
                )
            )
    await db.flush()
    return copy


# ── Describing a list's term ─────────────────────────────────────────────────


async def describe(db: AsyncSession, reading_list: ReadingList) -> dict:
    """Term, section and where-it-came-from details for a list (staff views)."""
    out: dict = {"kind": reading_list.kind, "term": None, "section": None, "copied_from": None,
                 "copied_at": reading_list.copied_at}
    if reading_list.course_offering_id:
        row = (
            await db.execute(
                select(CourseOffering.section, CourseOffering.lms_code, Term.code, Term.name)
                .outerjoin(Term, Term.id == CourseOffering.term_id)
                .where(CourseOffering.id == reading_list.course_offering_id)
            )
        ).first()
        if row:
            out["term"] = {"code": row.code, "name": row.name} if row.code else None
            out["section"] = row.section or row.lms_code
    if reading_list.copied_from_list_id:
        source = (
            await db.execute(
                select(ReadingList.id, ReadingList.title, ReadingList.kind, Term.name)
                .outerjoin(CourseOffering, CourseOffering.id == ReadingList.course_offering_id)
                .outerjoin(Term, Term.id == CourseOffering.term_id)
                .where(ReadingList.id == reading_list.copied_from_list_id)
            )
        ).first()
        if source:
            out["copied_from"] = {"id": source.id, "title": source.title, "kind": source.kind, "term_name": source.name}
    return out


async def offerings_count(db: AsyncSession, term_id: uuid.UUID) -> int:
    return await db.scalar(select(func.count()).select_from(CourseOffering).where(CourseOffering.term_id == term_id))
