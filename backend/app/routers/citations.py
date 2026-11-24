import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import Citation, ImportItem, User
from app.schemas.lists import CitationCreate, CitationReorder, CitationUpdate, StaffCitation
from app.services import lists_service as svc

router = APIRouter()

# Access is any active user in the list's organization (see routers/lists.py).


@router.post(
    "/sections/{section_id}/citations",
    response_model=StaffCitation,
    status_code=status.HTTP_201_CREATED,
    summary="Add a citation",
)
async def create_citation(
    section_id: uuid.UUID,
    body: CitationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a citation at the end of a section."""
    section = await svc.get_section(db, current_user, section_id)
    citation = Citation(
        list_section_id=section.id,
        sort_order=await svc.next_sort_order(db, Citation.sort_order, Citation.list_section_id == section.id),
        source_system="manual",
        created_by=current_user.id,
        **body.to_model_fields(),
    )
    db.add(citation)
    await svc.touch_list(db, section.reading_list_id)
    await db.flush()
    await db.refresh(citation)
    return citation


@router.patch("/citations/{citation_id}", response_model=StaffCitation, summary="Update a citation")
async def update_citation(
    citation_id: uuid.UUID,
    body: CitationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update citation fields. Sending `list_section_id` moves it to the end of that section."""
    citation = await svc.get_citation(db, current_user, citation_id)
    source = await svc.get_section(db, current_user, citation.list_section_id)
    fields = body.to_model_fields()

    target_id = fields.pop("list_section_id", None)
    if target_id is not None and target_id != citation.list_section_id:
        target = await svc.get_section(db, current_user, target_id)
        if target.reading_list_id != source.reading_list_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Citations can only be moved between sections of the same reading list",
            )
        citation.list_section_id = target.id
        citation.sort_order = await svc.next_sort_order(
            db, Citation.sort_order, Citation.list_section_id == target.id
        )

    for field, value in fields.items():
        setattr(citation, field, value)
    await svc.touch_list(db, source.reading_list_id)
    await db.flush()
    await db.refresh(citation)
    return citation


@router.delete(
    "/citations/{citation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a citation",
)
async def delete_citation(
    citation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    citation = await svc.get_citation(db, current_user, citation_id)
    section = await svc.get_section(db, current_user, citation.list_section_id)
    # Keep import history, but detach it from the citation being deleted
    await db.execute(
        update(ImportItem)
        .where(ImportItem.resulting_citation_id == citation.id)
        .values(resulting_citation_id=None)
    )
    await svc.touch_list(db, section.reading_list_id)
    await db.delete(citation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sections/{section_id}/citations/reorder",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reorder citations in a section",
)
async def reorder_citations(
    section_id: uuid.UUID,
    body: CitationReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set citation order. `citation_ids` must name every citation in the section exactly once."""
    section = await svc.get_section(db, current_user, section_id)
    citations = (await db.scalars(select(Citation).where(Citation.list_section_id == section.id))).all()
    svc.apply_order(citations, body.citation_ids, "citation_ids")
    await svc.touch_list(db, section.reading_list_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
