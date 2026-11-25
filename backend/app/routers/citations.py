import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_extension_user
from app.models.models import Citation, CitationEvent, ImportItem, User
from app.schemas.lists import (
    BOUND_EDITABLE_FIELDS,
    CitationCreate,
    CitationReorder,
    CitationUpdate,
    StaffCitation,
)
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
    current_user: User = Depends(get_extension_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a citation at the end of a section."""
    section = await svc.get_section(db, current_user, section_id, need="lists.edit")
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
    citation = await svc.get_citation(db, current_user, citation_id, need="lists.edit")
    source = await svc.get_section(db, current_user, citation.list_section_id, need="lists.edit")
    fields = body.to_model_fields()

    if citation.is_bound:
        # Bibliographic fields follow the library's record. Unchanged values are fine
        # (forms send everything); changing one needs an unlink first.
        changed = [
            name
            for name, value in fields.items()
            if name not in BOUND_EDITABLE_FIELDS and getattr(citation, name) != value
        ]
        if changed:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This citation comes from your library's catalogue and updates automatically. "
                "Unlink it from the catalogue record to edit these fields.",
            )

    target_id = fields.pop("list_section_id", None)
    if target_id is not None and target_id != citation.list_section_id:
        target = await svc.get_section(db, current_user, target_id, need="lists.edit")
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
    citation = await svc.get_citation(db, current_user, citation_id, need="lists.edit")
    section = await svc.get_section(db, current_user, citation.list_section_id, need="lists.edit")
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
    section = await svc.get_section(db, current_user, section_id, need="lists.edit")
    citations = (await db.scalars(select(Citation).where(Citation.list_section_id == section.id))).all()
    svc.apply_order(citations, body.citation_ids, "citation_ids")
    await svc.touch_list(db, section.reading_list_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/citations/{citation_id}/unlink", response_model=StaffCitation, summary="Unlink from the source record")
async def unlink_citation(
    citation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detach a citation from its library record so its fields can be edited.

    It keeps its current metadata and provenance but no longer syncs. This can't
    be undone; to rebind, add the record again.
    """
    citation = await svc.get_citation(db, current_user, citation_id, need="lists.edit")
    if not citation.is_bound:
        raise HTTPException(status.HTTP_409_CONFLICT, "This citation isn't linked to a library record")
    section = await svc.get_section(db, current_user, citation.list_section_id, need="lists.edit")
    citation.source_status = "unlinked"
    await svc.touch_list(db, section.reading_list_id)
    await db.flush()
    await db.refresh(citation)
    return citation


class CitationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    kind: str
    source_system: str | None = None
    details: dict


@router.get(
    "/citations/{citation_id}/history",
    response_model=list[CitationEventOut],
    summary="Changes made by the catalogue sync",
)
async def citation_history(
    citation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Newest first: updates from the catalogue, and records going missing or coming back."""
    citation = await svc.get_citation(db, current_user, citation_id)
    events = await db.scalars(
        select(CitationEvent)
        .where(CitationEvent.citation_id == citation.id)
        .order_by(CitationEvent.occurred_at.desc(), CitationEvent.id.desc())
        .limit(50)
    )
    return list(events)
