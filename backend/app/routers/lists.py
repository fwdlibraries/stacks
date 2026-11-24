import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import College, CourseTemplate, Department, ListSection, ReadingList, User
from app.schemas.lists import ReadingListSummary, StaffReadingList

router = APIRouter()

# TODO: remaining endpoints (create, update, publish, sections, reorder); see
# docs/architecture/design.md § API Layer. Access is currently any active user in
# the list's organization; per-role permissions (require_permission) come later.


def _org_lists(user: User):
    """Reading lists belonging to the user's organization."""
    return (
        select(ReadingList)
        .join(ReadingList.course_template)
        .join(CourseTemplate.department)
        .join(Department.college)
        .where(College.organization_id == user.organization_id)
    )


@router.get("/lists", response_model=list[ReadingListSummary], summary="Reading lists")
async def list_reading_lists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reading lists in the current user's organization, most recently updated first."""
    result = await db.scalars(_org_lists(current_user).order_by(ReadingList.updated_at.desc()))
    return result.all()


@router.get(
    "/lists/{list_id}/full",
    response_model=StaffReadingList,
    summary="Reading list with sections and citations",
)
async def get_reading_list_full(
    list_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compound document: the list, its sections and their citations, including staff notes."""
    reading_list = await db.scalar(
        _org_lists(current_user)
        .where(ReadingList.id == list_id)
        .options(selectinload(ReadingList.sections).selectinload(ListSection.citations))
    )
    if reading_list is None:
        # 404 rather than 403 for other organizations' lists: don't confirm they exist
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reading list not found")
    return reading_list
