import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import (
    Citation,
    CourseTemplate,
    ImportItem,
    ListSection,
    LtiDeepLink,
    ReadingList,
    ScopeType,
    Term,
    User,
)
from app.schemas.lists import (
    ListCopy,
    ReadingListSummary,
    ReadingListUpdate,
    SectionCreate,
    SectionReorder,
    SectionUpdate,
    StaffReadingList,
    StaffSection,
    TermOut,
)
from app.services import access, links, terms
from app.services import lists_service as svc

router = APIRouter()

# Access comes from the user's roles and their scopes (app/services/access.py);
# lists_service checks them on every lookup. Lists are created by LTI launches and by
# copying a list into another term.


async def _annotate(db: AsyncSession, user: User, reading_list: ReadingList) -> ReadingList:
    """Add what the user may do with the list, and its term and copy history."""
    for flag, value in (await svc.permissions_on(db, user, reading_list.id)).items():
        setattr(reading_list, flag, value)
    for field, value in (await terms.describe(db, reading_list)).items():
        if field not in ("kind", "copied_at"):
            setattr(reading_list, field, value)
    # Copying into another term needs lists.edit for the whole course (see copy_reading_list)
    grants = await access.load_grants(db, user)
    reading_list.can_copy = await access.holds_at(
        db, grants, "lists.edit", ScopeType.course_template, reading_list.course_template_id
    )
    return reading_list


# ── Reading lists ────────────────────────────────────────────────────────────

@router.get("/lists", response_model=list[ReadingListSummary], summary="Reading lists")
async def list_reading_lists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reading lists in the current user's organization, most recently updated first."""
    lists = (await db.scalars((await svc.visible_lists_query(db, current_user)).order_by(ReadingList.updated_at.desc()))).all()
    for reading_list in lists:
        await _annotate(db, current_user, reading_list)
    return lists


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
    await _annotate(db, current_user, reading_list)
    return links.annotate(reading_list, await links.load_link_settings(db, current_user.organization_id))


@router.patch("/lists/{list_id}", response_model=ReadingListSummary, summary="Update list details")
async def update_reading_list(
    list_id: uuid.UUID,
    body: ReadingListUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fields = body.model_dump(exclude_unset=True)
    # Who can see a list is a publishing decision, not an edit
    need = "lists.publish" if "visibility" in fields else "lists.edit"
    reading_list = await svc.get_list(db, current_user, list_id, need=need)
    if need == "lists.publish" and set(fields) - {"visibility"}:
        await svc.require(db, current_user, list_id, "lists.edit")
    for field, value in fields.items():
        setattr(reading_list, field, value)
    await db.flush()
    await db.refresh(reading_list)
    return reading_list


async def _set_published(db: AsyncSession, user: User, list_id: uuid.UUID, published: bool):
    reading_list = await svc.get_list(db, user, list_id, need="lists.publish")
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


# ── Terms and copying ────────────────────────────────────────────────────────

@router.get("/terms", response_model=list[TermOut], summary="Terms")
async def list_terms(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The organization's terms, newest first (for choosing where to copy a list)."""
    rows = await db.scalars(
        select(Term)
        .where(Term.organization_id == current_user.organization_id)
        .order_by(Term.starts_on.desc().nulls_last(), Term.code.desc())
    )
    return rows.all()


@router.post(
    "/lists/{list_id}/copy",
    response_model=ReadingListSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a list into another term",
)
async def copy_reading_list(
    list_id: uuid.UUID,
    body: ListCopy,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A draft copy of the list for the same course in another term (and section, if
    given): details, sections, citations and notes, with the same item keys. Needs
    lists.edit for the whole course, not just one offering. 409 if that term's
    section already has its own list."""
    source = await svc.get_list(db, current_user, list_id)
    term = await db.scalar(select(Term).where(Term.id == body.term_id, Term.organization_id == current_user.organization_id))
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")
    grants = await access.load_grants(db, current_user)
    if not await access.holds_at(db, grants, "lists.edit", ScopeType.course_template, source.course_template_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to make lists for this course")
    template = await db.get(CourseTemplate, source.course_template_id)
    offering = await terms.offering_for(db, template, term, body.section)
    try:
        copy = await terms.copy_list(db, source.id, offering, current_user)
    except terms.AlreadyHasList as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": f"{term.name} already has its own list for this course", "list_id": str(exc.existing.id)},
        ) from exc
    await db.refresh(copy)
    return await _annotate(db, current_user, copy)


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
    reading_list = await svc.get_list(db, current_user, list_id, need="lists.edit")
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
    reading_list = await svc.get_list(db, current_user, list_id, need="lists.edit")
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
    section = await svc.get_section(db, current_user, section_id, need="lists.edit")
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
    section = await svc.get_section(db, current_user, section_id, need="lists.edit")
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
