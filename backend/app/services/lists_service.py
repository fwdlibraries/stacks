"""Permission-checked lookups and shared helpers for reading list editing.

Every lookup joins up to the organization and checks the user's role scopes
(app/services/access.py) for the permission the caller needs. A list the user
can't even view is a 404, like one in another organization, so its existence
isn't confirmed; one they can view but not change is a 403.
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
from app.services.access import list_condition, load_grants


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


NEEDS = {
    "lists.edit": "edit",
    "lists.publish": "publish or change the visibility of",
    "lists.view": "view",
}


async def visible_lists_query(db: AsyncSession, user: User, permission: str = "lists.view"):
    """Reading lists in the user's organization on which they hold `permission`."""
    grants = await load_grants(db, user)
    return org_lists_query(user).where(list_condition(grants, permission))


async def require(db: AsyncSession, user: User, list_id: uuid.UUID, need: str, what: str = "Reading list") -> None:
    """404 unless the user can view the list; 403 unless they also hold `need`."""
    grants = await load_grants(db, user)
    row = (
        await db.execute(
            org_lists_query(user)
            .with_only_columns(
                list_condition(grants, "lists.view").label("view"), list_condition(grants, need).label("need")
            )
            .where(ReadingList.id == list_id)
        )
    ).first()
    if row is None or not row.view:
        raise _not_found(what)
    if not row.need:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"You don't have permission to {NEEDS.get(need, need)} this reading list"
        )


async def permissions_on(db: AsyncSession, user: User, list_id: uuid.UUID) -> dict[str, bool]:
    """What the user may do with one list, for the editor (hide what they can't use)."""
    grants = await load_grants(db, user)
    row = (
        await db.execute(
            org_lists_query(user)
            .with_only_columns(
                list_condition(grants, "lists.edit").label("edit"),
                list_condition(grants, "lists.publish").label("publish"),
            )
            .where(ReadingList.id == list_id)
        )
    ).first()
    return {"can_edit": bool(row and row.edit), "can_publish": bool(row and row.publish)}


async def get_list(
    db: AsyncSession, user: User, list_id: uuid.UUID, *, full: bool = False, need: str = "lists.view"
) -> ReadingList:
    await require(db, user, list_id, need)
    query = org_lists_query(user).where(ReadingList.id == list_id)
    if full:
        # populate_existing: reload collections even if the list is already in the session
        query = query.options(
            selectinload(ReadingList.sections).selectinload(ListSection.citations)
        ).execution_options(populate_existing=True)
    return await db.scalar(query)


async def get_section(db: AsyncSession, user: User, section_id: uuid.UUID, *, need: str = "lists.view") -> ListSection:
    section = await db.scalar(
        select(ListSection)
        .join(ListSection.reading_list)
        .where(ListSection.id == section_id)
        .where(ReadingList.id.in_(org_lists_query(user).with_only_columns(ReadingList.id)))
    )
    if section is None:
        raise _not_found("Section")
    await require(db, user, section.reading_list_id, need, "Section")
    return section


async def get_citation(db: AsyncSession, user: User, citation_id: uuid.UUID, *, need: str = "lists.view") -> Citation:
    row = (
        await db.execute(
            select(Citation, ListSection.reading_list_id)
            .join(Citation.section)
            .where(Citation.id == citation_id)
            .where(ListSection.reading_list_id.in_(org_lists_query(user).with_only_columns(ReadingList.id)))
        )
    ).first()
    if row is None:
        raise _not_found("Citation")
    await require(db, user, row.reading_list_id, need, "Citation")
    return row.Citation


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
