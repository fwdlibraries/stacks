"""Rollover stage 2: importing sections and primaries, and finding each section's primary
(docs/design/rollover.md, "Matching sections to primaries").

- A loader file (the Alma/Leganto course loader layout: CourseID, Course, Section_ID,
  Academic_Department, Term1, INSTR1-10, OPERATION, OLD_COURSE_CODE, ...) adds the
  term's live sections: a course offering with its LMS shell code, and a rollover item.
- A list of primary shells (an LMS export, or one code per line) adds primaries. Their
  codes are read with the organization's primary code pattern, e.g.
  "{subject}{number}_{mode}_{length}_PRIMARY".
- Each section's primary is found by the first rule that gives exactly one answer:
  manual → file (OLD_COURSE_CODE) → remembered → rule (built code) → only one fits.
  Anything else waits in the "needs a source" queue.

Nothing here is specific to one institution: column names, the pattern and the
part-of-term → length table are organization settings.
"""
import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    College,
    CourseOffering,
    CourseTemplate,
    Department,
    Organization,
    Primary,
    RememberedMatch,
    RolloverItem,
    Term,
    User,
)
from app.services import tenancy, terms

STATUSES = ("needs_source", "in_review", "approved", "skipped")
MATCH_SOURCES = ("manual", "file", "remembered", "rule", "only_one")
# Statuses matching may still change; approved and skipped items are librarians' decisions
OPEN = ("needs_source", "in_review")

# ── Settings ─────────────────────────────────────────────────────────────────


def header_key(name: str) -> str:
    """Column names compared loosely: 'Section_ID', 'Section ID' and 'sectionid' are one."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


class RolloverSettings(BaseModel):
    """organizations.settings['rollover']."""

    model_config = ConfigDict(extra="ignore")

    # How primary shells are coded; must include {subject} and {number}
    primary_code_pattern: str | None = Field(default=None, max_length=120)
    # Loader column holding the course's subject and number ("GEO 101" → GEO101)
    course_column: str = Field(default="SEARCH_ID1", max_length=64)
    # Loader column holding the part of term, and what each value means for length
    part_of_term_column: str = Field(default="Term1", max_length=64)
    lengths: dict[str, str] = Field(default_factory=dict)

    @field_validator("primary_code_pattern")
    @classmethod
    def _pattern(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        compile_primary_pattern(value.strip())
        return value.strip()

    @field_validator("course_column", "part_of_term_column")
    @classmethod
    def _column(cls, value: str) -> str:
        if not header_key(value):
            raise ValueError("Enter a column name")
        return value.strip()

    @field_validator("lengths")
    @classmethod
    def _lengths(cls, value: dict[str, str]) -> dict[str, str]:
        out = {}
        for part, length in value.items():
            part, length = str(part).strip().upper(), str(length).strip().upper()
            if part and length:
                out[part] = length
        if len(out) > 100:
            raise ValueError("Up to 100 part-of-term values")
        return out


async def get_settings(db: AsyncSession, organization_id: uuid.UUID) -> RolloverSettings:
    raw = await db.scalar(select(Organization.settings).where(Organization.id == organization_id))
    return RolloverSettings.model_validate(tenancy.OrgSettings.model_validate(raw or {}).rollover or {})


async def save_settings(db: AsyncSession, organization_id: uuid.UUID, value: RolloverSettings) -> None:
    org = await db.get(Organization, organization_id)
    org.settings = {**(org.settings or {}), "rollover": value.model_dump()}
    await db.flush()


# ── Primary codes ────────────────────────────────────────────────────────────

PRIMARY_FIELDS = {"subject": r"[A-Za-z]+", "number": r"[0-9]+[A-Za-z]?", "mode": r"[A-Za-z0-9]+",
                  "length": r"[A-Za-z0-9]+"}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def compile_primary_pattern(pattern: str) -> re.Pattern[str]:
    """'{subject}{number}_{mode}_{length}_PRIMARY' → a regular expression for whole codes."""
    names = _PLACEHOLDER.findall(pattern)
    unknown = sorted(set(names) - set(PRIMARY_FIELDS))
    if unknown:
        raise terms.PatternError(
            f"Unknown placeholder {{{unknown[0]}}}; use {', '.join('{' + f + '}' for f in PRIMARY_FIELDS)}"
        )
    if not {"subject", "number"} <= set(names):
        raise terms.PatternError("The pattern needs {subject} and {number}")
    if len(names) != len(set(names)):
        raise terms.PatternError("Use each placeholder once")
    out, pos = [], 0
    for match in _PLACEHOLDER.finditer(pattern):
        out.append(re.escape(pattern[pos : match.start()]))
        out.append(f"(?P<{match.group(1)}>{PRIMARY_FIELDS[match.group(1)]})")
        pos = match.end()
    out.append(re.escape(pattern[pos:]))
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


@dataclass
class PrimaryCode:
    code: str
    course: str  # SUBJECTNUMBER, e.g. GEO101
    subject: str
    mode: str | None = None
    length: str | None = None


def parse_primary_code(pattern: str | None, code: str | None) -> PrimaryCode | None:
    if not pattern or not code:
        return None
    try:
        match = compile_primary_pattern(pattern).match(code.strip())
    except terms.PatternError:
        return None
    if match is None:
        return None
    parts = {k: (v.upper() if v else None) for k, v in match.groupdict().items()}
    return PrimaryCode(
        code=code.strip().upper(), course=parts["subject"] + parts["number"], subject=parts["subject"],
        mode=parts.get("mode"), length=parts.get("length"),
    )


def build_primary_code(pattern: str, course: str, mode: str, length: str) -> str | None:
    """The code a primary would have, from the section's course, mode and length."""
    split = re.fullmatch(r"([A-Za-z]+)([0-9]+[A-Za-z]?)", course)
    if not split:
        return None
    values = {"subject": split.group(1), "number": split.group(2), "mode": mode, "length": length}
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], pattern).upper()


def course_key(raw: str | None) -> str:
    """'GEO 101' → 'GEO101': how courses are compared."""
    return re.sub(r"\s+", "", str(raw or "")).upper()


# ── Reading files ────────────────────────────────────────────────────────────


class FileProblem(ValueError):
    """The file can't be read at all (no rows, or a required column is missing)."""


def read_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Header and rows of a CSV or tab-separated file. Keys are header_key(column)."""
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise FileProblem("The file is empty")
    first = lines[0]
    delimiter = max(",\t;|", key=first.count) if any(c in first for c in ",\t;|") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader)
    keys = [header_key(h) for h in header]
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        rows.append({k: v.strip() for k, v in zip(keys, values, strict=False) if k})
    return header, rows


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


# ── Courses and offerings ────────────────────────────────────────────────────


async def find_course(db: AsyncSession, organization_id: uuid.UUID, course: str) -> CourseTemplate | None:
    return await db.scalar(
        select(CourseTemplate)
        .join(CourseTemplate.department)
        .join(Department.college)
        .where(
            College.organization_id == organization_id,
            func.upper(func.replace(CourseTemplate.code, " ", "")) == course,
        )
        .order_by(CourseTemplate.created_at)
        .limit(1)
    )


async def _department(db: AsyncSession, organization_id: uuid.UUID, *hints: str | None) -> Department:
    """The department whose code or name is one of `hints`, else the LMS default one."""
    for hint in hints:
        if not hint:
            continue
        found = await db.scalar(
            select(Department)
            .join(Department.college)
            .where(
                College.organization_id == organization_id,
                (func.lower(Department.code) == hint.lower()) | (func.lower(Department.name) == hint.lower()),
            )
            .limit(1)
        )
        if found:
            return found
    from app.services.lti_service import _default_department  # lti_service imports terms

    return await _default_department(db, organization_id)


async def course_for(
    db: AsyncSession, organization_id: uuid.UUID, course: str, name: str | None = None, *hints: str | None
) -> CourseTemplate:
    template = await find_course(db, organization_id, course)
    if template is None:
        department = await _department(db, organization_id, *hints)
        template = CourseTemplate(department_id=department.id, code=course, name=(name or course).strip())
        db.add(template)
        await db.flush()
    elif name and template.name == template.code:
        template.name = name.strip()  # created from a primary code; the loader knows the title
    return template


# ── Importing primaries ──────────────────────────────────────────────────────


@dataclass
class Skipped:
    line: int
    code: str
    reason: str


@dataclass
class PrimariesResult:
    added: int = 0
    updated: int = 0
    skipped: list[Skipped] = field(default_factory=list)


async def add_primary(
    db: AsyncSession, organization_id: uuid.UUID, parsed: PrimaryCode, *, origin: str, name: str | None = None,
    lms_org_unit_id: str | None = None, lms_department: str | None = None,
) -> tuple[Primary, bool]:
    """The primary with this code, created (with its course) if new. Returns (primary, created)."""
    primary = await db.scalar(
        select(Primary).where(Primary.organization_id == organization_id, Primary.code == parsed.code)
    )
    created = primary is None
    if created:
        template = await course_for(db, organization_id, parsed.course, None, parsed.subject)
        primary = Primary(organization_id=organization_id, course_template_id=template.id, code=parsed.code,
                          origin=origin)
        db.add(primary)
    primary.mode, primary.length = parsed.mode, parsed.length
    primary.name = name or primary.name
    primary.lms_org_unit_id = lms_org_unit_id or primary.lms_org_unit_id
    primary.lms_department = lms_department or primary.lms_department
    await db.flush()
    return primary, created


async def import_primaries(db: AsyncSession, organization_id: uuid.UUID, text: str) -> PrimariesResult:
    """A list of primary shells: an LMS export with a code column (and optionally name,
    org unit ID, department), or just one code per line."""
    settings = await get_settings(db, organization_id)
    if not settings.primary_code_pattern:
        raise FileProblem("Set how primary shells are coded first")
    header, rows = read_table(text)
    keys = {header_key(h) for h in header}
    code_columns = ("code", "orgunitcode", "coursecode", "coursecodeprimary", "primary")
    if not keys & set(code_columns):
        # No header: one code per line (first column)
        rows = [{"code": line.split(",")[0].split("\t")[0].strip()} for line in text.lstrip("﻿").splitlines()
                if line.strip()]
        line_offset = 1
    else:
        line_offset = 2
    result = PrimariesResult()
    for n, row in enumerate(rows):
        code = _first(row, *code_columns)
        parsed = parse_primary_code(settings.primary_code_pattern, code)
        if parsed is None:
            if code:
                result.skipped.append(Skipped(n + line_offset, code, "Doesn't look like a primary code"))
            continue
        _, created = await add_primary(
            db, organization_id, parsed, origin="import",
            name=_first(row, "name", "orgunitname", "coursename", "title") or None,
            lms_org_unit_id=_first(row, "orgunitid", "id", "orgunit") or None,
            lms_department=_first(row, "department", "brightspacedepartment", "parentdepartment") or None,
        )
        if created:
            result.added += 1
        else:
            result.updated += 1
    return result


# ── Importing a loader file ──────────────────────────────────────────────────

SHELL_COLUMNS = ("courseid", "coursecode")
NAME_COLUMNS = ("course", "coursetitle", "coursename")
SECTION_COLUMNS = ("sectionid", "section")
DEPARTMENT_COLUMNS = ("academicdepartment", "department")
OLD_CODE_COLUMNS = ("oldcoursecode",)
INSTRUCTOR_COLUMNS = tuple(f"{p}{n}" for n in range(1, 11) for p in ("instr", "instructor"))


@dataclass
class SectionsResult:
    added: int = 0
    updated: int = 0
    skipped: list[Skipped] = field(default_factory=list)
    matched: dict[str, int] = field(default_factory=dict)
    needs_source: int = 0


async def import_loader(db: AsyncSession, organization_id: uuid.UUID, term: Term, text: str) -> SectionsResult:
    """The term's sections from a course loader file. Importing again updates sections
    already imported; their librarians' decisions are kept."""
    settings = await get_settings(db, organization_id)
    header, rows = read_table(text)
    keys = {header_key(h) for h in header}
    if not keys & set(SHELL_COLUMNS):
        raise FileProblem("The file needs a CourseID column: the live LMS shell code, e.g. 40112.202710")
    course_column = header_key(settings.course_column)
    part_column = header_key(settings.part_of_term_column)
    section_pattern = await terms.section_code_pattern(db, organization_id)

    result = SectionsResult()
    seen: set[str] = set()
    items: list[RolloverItem] = []
    for n, row in enumerate(rows, start=2):
        shell = _first(row, *SHELL_COLUMNS)
        if not shell:
            continue
        if row.get("operation", "").upper() == "DELETE":
            result.skipped.append(Skipped(n, shell, "Marked DELETE"))
            continue
        if shell.lower() in seen:
            result.skipped.append(Skipped(n, shell, "Already in this file"))
            continue
        seen.add(shell.lower())
        parsed = terms.parse_section_code(section_pattern, shell)
        if parsed and parsed.term != term.code:
            result.skipped.append(Skipped(n, shell, f"This section is in term {parsed.term}, not {term.code}"))
            continue
        course = course_key(row.get(course_column) or (parsed.course if parsed else ""))
        if not course:
            result.skipped.append(Skipped(n, shell, f"No course code (the {settings.course_column} column)"))
            continue
        department = _first(row, *DEPARTMENT_COLUMNS) or None
        template = await course_for(
            db, organization_id, course, _first(row, *NAME_COLUMNS) or None, department,
            re.match(r"[A-Z]+", course).group(0) if re.match(r"[A-Z]+", course) else None,
        )

        offering = await db.scalar(
            select(CourseOffering)
            .join(CourseOffering.template)
            .join(CourseTemplate.department)
            .join(Department.college)
            .where(
                College.organization_id == organization_id,
                CourseOffering.term == term.code,
                func.lower(CourseOffering.lms_code) == shell.lower(),
            )
            .limit(1)
        )
        if offering is None:
            offering = CourseOffering(
                course_template_id=template.id, term=term.code, term_id=term.id, lms_code=shell,
                section=(parsed.crn or parsed.section if parsed else None) or _first(row, *SECTION_COLUMNS) or None,
            )
            db.add(offering)
            await db.flush()

        item = await db.scalar(
            select(RolloverItem).where(RolloverItem.term_id == term.id, RolloverItem.course_offering_id == offering.id)
        )
        if item is None:
            item = RolloverItem(term_id=term.id, course_offering_id=offering.id, status="needs_source")
            db.add(item)
            result.added += 1
        else:
            result.updated += 1
        part = row.get(part_column, "").upper() or None
        item.part_of_term = part
        item.length = settings.lengths.get(part) if part else None
        item.department = department
        item.instructors = [row[c] for c in INSTRUCTOR_COLUMNS if row.get(c)]
        item.file_primary_code = _first(row, *OLD_CODE_COLUMNS).upper() or None
        item.row = {h: v for h, v in zip(header, (row.get(header_key(h), "") for h in header), strict=True) if v}
        items.append(item)
    await db.flush()

    for item in items:
        await match(db, organization_id, item, settings)
        if item.primary_id:
            result.matched[item.match_source] = result.matched.get(item.match_source, 0) + 1
        else:
            result.needs_source += 1
    return result


# ── Matching ─────────────────────────────────────────────────────────────────


async def _primary_by_code(db: AsyncSession, organization_id: uuid.UUID, code: str) -> Primary | None:
    return await db.scalar(select(Primary).where(Primary.organization_id == organization_id, Primary.code == code.upper()))


async def match(
    db: AsyncSession, organization_id: uuid.UUID, item: RolloverItem, settings: RolloverSettings | None = None
) -> None:
    """Find the item's primary (rules in the module docstring) and set its problems.
    Approved and skipped items, and manual choices, keep their primary."""
    settings = settings or await get_settings(db, organization_id)
    offering = await db.get(CourseOffering, item.course_offering_id)
    template_id = offering.course_template_id
    problems: list[str] = []
    unmatched: list[str] = []  # only shown while nothing is matched
    if item.part_of_term and not item.length:
        problems.append(f"Part of term {item.part_of_term} has no length set")

    found: Primary | None = None
    source: str | None = None
    if item.match_source == "manual" and item.primary_id:
        found, source = await db.get(Primary, item.primary_id), "manual"

    # File: the loader names the primary
    if found is None and item.file_primary_code:
        found = await _primary_by_code(db, organization_id, item.file_primary_code)
        if found is None:
            parsed = parse_primary_code(settings.primary_code_pattern, item.file_primary_code)
            if parsed:
                found, _ = await add_primary(db, organization_id, parsed, origin="file")
            else:
                problems.append(f"The file names {item.file_primary_code}, which isn't a primary code")
        if found is not None:
            source = "file"

    # Remembered: a librarian's choice for this course variant in an earlier term
    if found is None:
        remembered = await db.scalar(
            select(RememberedMatch).where(
                RememberedMatch.course_template_id == template_id,
                RememberedMatch.length == (item.length or ""),
                RememberedMatch.mode == (item.mode or ""),
            )
        )
        if remembered:
            found, source = await db.get(Primary, remembered.primary_id), "remembered"

    # Rule: the code the primary would have
    if found is None and settings.primary_code_pattern and item.mode and item.length:
        template = await db.get(CourseTemplate, template_id)
        code = build_primary_code(settings.primary_code_pattern, course_key(template.code), item.mode, item.length)
        if code:
            found = await _primary_by_code(db, organization_id, code)
            source = "rule" if found else None

    # Only one fits: the course has a single primary of the section's length
    if found is None:
        query = select(Primary).where(Primary.course_template_id == template_id)
        if item.length:
            query = query.where(Primary.length == item.length)
        if item.mode:
            query = query.where(Primary.mode == item.mode)
        candidates = list((await db.scalars(query.order_by(Primary.code))).all())
        if len(candidates) == 1:
            found, source = candidates[0], "only_one"
        elif candidates:
            unmatched.append("Several primaries fit: " + ", ".join(p.code for p in candidates))
        else:
            unmatched.append("The course has no primary" + (f" of length {item.length}" if item.length else ""))
        problems += unmatched

    if item.status in OPEN:
        item.primary_id = found.id if found else None
        item.match_source = source if found else None
        item.status = "in_review" if found else "needs_source"
    current = found if item.status in OPEN else (await db.get(Primary, item.primary_id) if item.primary_id else None)
    if current is not None:
        problems = [p for p in problems if p not in unmatched]
        if current.course_template_id != template_id:
            problems.append(f"{current.code} is another course's primary")
    item.problems = problems
    await db.flush()


async def rematch_term(db: AsyncSession, organization_id: uuid.UUID, term: Term) -> None:
    settings = await get_settings(db, organization_id)
    for item in (await db.scalars(select(RolloverItem).where(RolloverItem.term_id == term.id))).all():
        await match(db, organization_id, item, settings)


async def choose(
    db: AsyncSession, organization_id: uuid.UUID, item: RolloverItem, primary: Primary | None, user: User,
    *, remember: bool,
) -> None:
    """A librarian picks the item's primary (or clears it, which re-runs the rules)."""
    now = datetime.now(UTC)
    item.decided_by, item.decided_at = user.id, now
    if primary is None:
        item.match_source, item.primary_id = None, None
        if item.status not in OPEN:
            item.status = "needs_source"
        await match(db, organization_id, item)
        return
    item.primary_id, item.match_source = primary.id, "manual"
    if item.status == "needs_source":
        item.status = "in_review"
    if remember:
        offering = await db.get(CourseOffering, item.course_offering_id)
        existing = await db.scalar(
            select(RememberedMatch).where(
                RememberedMatch.course_template_id == offering.course_template_id,
                RememberedMatch.length == (item.length or ""),
                RememberedMatch.mode == (item.mode or ""),
            )
        )
        if existing is None:
            db.add(RememberedMatch(
                organization_id=organization_id, course_template_id=offering.course_template_id,
                length=item.length or "", mode=item.mode or "", primary_id=primary.id, created_by=user.id,
            ))
        else:
            existing.primary_id, existing.created_by = primary.id, user.id
    await match(db, organization_id, item)


def set_status(item: RolloverItem, status: str, user: User) -> None:
    """Approve, skip, or return to review. Approving needs a primary."""
    if status == "approved" and not item.primary_id:
        raise ValueError("Choose a primary before approving")
    if status in OPEN:
        status = "in_review" if item.primary_id else "needs_source"
    item.status = status
    item.decided_by, item.decided_at = user.id, datetime.now(UTC)
