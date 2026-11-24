"""Organization-scoped lookups and shared helpers for reading list editing.

Every lookup joins up to the organization, so a user can never read or change
another organization's lists, sections or citations. Not-found and
other-organization both raise 404, so IDs from other organizations aren't confirmed.
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Citation,
    College,
    CourseTemplate,
    Department,
    ListSection,
    ReadingList,
    User,
)


def org_lists_query(user: User):
    """Reading lists belonging to the user's organization."""
    return (
        select(ReadingList)
        .join(ReadingList.course_template)
        .join(CourseTemplate.department)
        .join(Department.college)
        .where(College.organization_id == user.organization_id)
    )


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


async def get_list(db: AsyncSession, user: User, list_id: uuid.UUID, *, full: bool = False) -> ReadingList:
    query = org_lists_query(user).where(ReadingList.id == list_id)
    if full:
        # populate_existing: reload collections even if the list is already in the session
        query = query.options(
            selectinload(ReadingList.sections).selectinload(ListSection.citations)
        ).execution_options(populate_existing=True)
    reading_list = await db.scalar(query)
    if reading_list is None:
        raise _not_found("Reading list")
    return reading_list


async def get_section(db: AsyncSession, user: User, section_id: uuid.UUID) -> ListSection:
    section = await db.scalar(
        select(ListSection)
        .join(ListSection.reading_list)
        .where(ListSection.id == section_id)
        .where(ReadingList.id.in_(org_lists_query(user).with_only_columns(ReadingList.id)))
    )
    if section is None:
        raise _not_found("Section")
    return section


async def get_citation(db: AsyncSession, user: User, citation_id: uuid.UUID) -> Citation:
    citation = await db.scalar(
        select(Citation)
        .join(Citation.section)
        .where(Citation.id == citation_id)
        .where(ListSection.reading_list_id.in_(org_lists_query(user).with_only_columns(ReadingList.id)))
    )
    if citation is None:
        raise _not_found("Citation")
    return citation


async def next_sort_order(db: AsyncSession, column, *where) -> int:
    current = await db.scalar(select(func.max(column)).where(*where))
    return 0 if current is None else current + 1


async def touch_list(db: AsyncSession, list_id: uuid.UUID) -> None:
    """Bump updated_at on the list when its sections or citations change."""
    await db.execute(update(ReadingList).where(ReadingList.id == list_id).values(updated_at=func.now()))


def apply_order(items, ordered_ids: list[uuid.UUID], what: str) -> None:
    """Set sort_order from ordered_ids, which must name every item exactly once."""
    by_id = {item.id: item for item in items}
    if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(by_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{what} must list every item exactly once",
        )
    for index, item_id in enumerate(ordered_ids):
        by_id[item_id].sort_order = index
