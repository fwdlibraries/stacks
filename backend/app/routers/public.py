"""Unauthenticated endpoints for the student reading list view (frontend public.html)."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.models import (
    College,
    CourseOffering,
    CourseTemplate,
    Department,
    ListSection,
    OfferingListOverride,
    Organization,
    ReadingList,
)
from app.schemas.public import PublicReadingList
from app.services import links, tenancy

router = APIRouter()

# Visibilities served without authentication. 'institution' lists need a signed-in
# user from the organization, which isn't implemented yet, so they 404 here.
PUBLIC_VISIBILITIES = {"public", "unlisted"}


@router.get(
    "/lists/{org_slug}/{course_code}/{term}",
    response_model=PublicReadingList,
    summary="Public reading list for a course offering",
)
async def get_public_list(
    org_slug: str,
    course_code: str,
    term: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant),
):
    """
    Resolve organization → course (code, case-insensitive) → offering (term) →
    reading list. An active offering-level override wins; otherwise the course's
    most recently updated list is used, preferring published lists.

    Unpublished lists return only their title and `is_published: false`, so the
    student view can say "not published yet" without exposing draft content.
    """
    # An organization's own hostname serves only its lists
    if tenant and tenant.by_domain and tenant.slug.lower() != org_slug.lower():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reading list not found")
    offering = await db.scalar(
        select(CourseOffering)
        .join(CourseOffering.template)
        .join(CourseTemplate.department)
        .join(Department.college)
        .join(College.organization)
        .where(
            Organization.slug == org_slug,
            func.lower(CourseTemplate.code) == course_code.lower(),
            CourseOffering.term == term,
        )
        .order_by(CourseOffering.section.nulls_first(), CourseOffering.created_at)
        .limit(1)
    )
    if offering is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reading list not found")

    load_sections = selectinload(ReadingList.sections).selectinload(ListSection.citations)

    reading_list = await db.scalar(
        select(ReadingList)
        .join(OfferingListOverride, OfferingListOverride.reading_list_id == ReadingList.id)
        .where(
            OfferingListOverride.course_offering_id == offering.id,
            OfferingListOverride.is_active.is_(True),
        )
        .options(load_sections)
        .limit(1)
    )
    if reading_list is None:
        reading_list = await db.scalar(
            select(ReadingList)
            .where(ReadingList.course_template_id == offering.course_template_id)
            .order_by(ReadingList.is_published.desc(), ReadingList.updated_at.desc())
            .options(load_sections)
            .limit(1)
        )

    if reading_list is None or reading_list.visibility not in PUBLIC_VISIBILITIES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reading list not found")

    if not reading_list.is_published:
        response.headers["Cache-Control"] = "no-store"
        return PublicReadingList(
            id=reading_list.id,
            title=reading_list.title,
            visibility=reading_list.visibility,
            is_published=False,
        )

    # Lists rarely change mid-term; a short shared cache absorbs class-wide traffic spikes
    response.headers["Cache-Control"] = "public, max-age=60"
    org_id = await db.scalar(select(Organization.id).where(Organization.slug == org_slug))
    links.annotate(reading_list, await links.load_link_settings(db, org_id))
    return PublicReadingList.model_validate(reading_list)
