import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import Citation, ImportItem, ListSection, LtiDeepLink, ReadingList, User
from app.schemas.lists import (
    ReadingListSummary,
    ReadingListUpdate,
    SectionCreate,
    SectionReorder,
    SectionUpdate,
    StaffReadingList,
    StaffSection,
)
from app.services import links
from app.services import lists_service as svc

router = APIRouter()

# Access is any active user in the list's organization; per-role permissions
# (require_permission) come later. Creating lists happens via LTI launch (TODO).


# ── Reading lists ────────────────────────────────────────────────────────────

@router.get("/lists", response_model=list[ReadingListSummary], summary="Reading lists")
async def list_reading_lists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reading lists in the current user's organization, most recently updated first."""
    result = await db.scalars(svc.org_lists_query(current_user).order_by(ReadingList.updated_at.desc()))
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
    reading_list = await svc.get_list(db, current_user, list_id, full=True)
    return links.annotate(reading_list, await links.load_link_settings(db, current_user.organization_id))


@router.patch("/lists/{list_id}", response_model=ReadingListSummary, summary="Update list details")
async def update_reading_list(
    list_id: uuid.UUID,
    body: ReadingListUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reading_list = await svc.get_list(db, current_user, list_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(reading_list, field, value)
    await db.flush()
    await db.refresh(reading_list)
    return reading_list


async def _set_published(db: AsyncSession, user: User, list_id: uuid.UUID, published: bool):
    reading_list = await svc.get_list(db, user, list_id)
    reading_list.is_published = published
    await db.flush()
    await db.refresh(reading_list)
    return reading_list


@router.post("/lists/{list_id}/publish", response_model=ReadingListSummary, summary="Publish list")
async def publish_reading_list(
    list_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Make the list visible to students (subject to its visibility setting)."""
    return await _set_published(db, current_user, list_id, True)


@router.post("/lists/{list_id}/unpublish", response_model=ReadingListSummary, summary="Unpublish list")
async def unpublish_reading_list(
    list_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hide the list's contents from students again."""
    return await _set_published(db, current_user, list_id, False)


# ── Sections ─────────────────────────────────────────────────────────────────

@router.post(
    "/lists/{list_id}/sections",
    response_model=StaffSection,
    status_code=status.HTTP_201_CREATED,
    summary="Add a section",
)
async def create_section(
    list_id: uuid.UUID,
    body: SectionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a section at the end of the list."""
    reading_list = await svc.get_list(db, current_user, list_id)
    section = ListSection(
        reading_list_id=reading_list.id,
        sort_order=await svc.next_sort_order(
            db, ListSection.sort_order, ListSection.reading_list_id == reading_list.id
        ),
        **body.model_dump(),
    )
    db.add(section)
    await svc.touch_list(db, reading_list.id)
    await db.flush()
    return StaffSection(
        id=section.id, title=section.title, description=section.description,
        sort_order=section.sort_order, citations=[],
    )


@router.post(
    "/lists/{list_id}/sections/reorder",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reorder sections",
)
async def reorder_sections(
    list_id: uuid.UUID,
    body: SectionReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set section order. `section_ids` must name every section of the list exactly once."""
    reading_list = await svc.get_list(db, current_user, list_id)
    sections = (
        await db.scalars(select(ListSection).where(ListSection.reading_list_id == reading_list.id))
    ).all()
    svc.apply_order(sections, body.section_ids, "section_ids")
    await svc.touch_list(db, reading_list.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/sections/{section_id}", response_model=StaffSection, summary="Update a section")
async def update_section(
    section_id: uuid.UUID,
    body: SectionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    section = await svc.get_section(db, current_user, section_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(section, field, value)
    await svc.touch_list(db, section.reading_list_id)
    await db.flush()
    citations = (
        await db.scalars(
            select(Citation).where(Citation.list_section_id == section.id).order_by(Citation.sort_order)
        )
    ).all()
    return StaffSection(
        id=section.id, title=section.title, description=section.description,
        sort_order=section.sort_order, citations=citations,
    )


@router.delete(
    "/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty section",
)
async def delete_section(
    section_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a section. Refused (409) while it still has citations."""
    section = await svc.get_section(db, current_user, section_id)
    citation_count = await db.scalar(
        select(func.count()).select_from(Citation).where(Citation.list_section_id == section.id)
    )
    if citation_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This section has {citation_count} citation(s). Move or delete them first.",
        )
    # Detach references that would otherwise block the delete
    await db.execute(
        update(ImportItem).where(ImportItem.target_section_id == section.id).values(target_section_id=None)
    )
    await db.execute(
        update(LtiDeepLink).where(LtiDeepLink.list_section_id == section.id).values(list_section_id=None)
    )
    await svc.touch_list(db, section.reading_list_id)
    await db.delete(section)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
