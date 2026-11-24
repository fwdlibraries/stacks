import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
    ResourceType,
)

URL = "/api/v1/public/lists/test-org/HIST101/fall-2026"


async def make_course(db: AsyncSession) -> tuple[CourseTemplate, CourseOffering]:
    org = Organization(name="Test University", slug="test-org")
    dept = Department(college=College(organization=org, name="Arts"), name="History")
    course = CourseTemplate(department=dept, code="HIST101", name="Historical Methods")
    offering = CourseOffering(template=course, term="fall-2026")
    db.add(org)
    await db.flush()
    return course, offering


def make_list(course: CourseTemplate, **kwargs) -> ReadingList:
    reading_list = ReadingList(course_template=course, title=kwargs.pop("title", "Readings"), **kwargs)
    section = ListSection(reading_list=reading_list, title="Required", sort_order=0)
    Citation(
        section=section,
        resource_type=ResourceType.book,
        title="What Is History?",
        author=["Carr, Edward Hallett"],
        staff_note="INTERNAL ONLY",
        student_note="Read chapter 1.",
    )
    return reading_list


@pytest.mark.asyncio
async def test_returns_published_list_without_staff_notes(client: AsyncClient, db_session: AsyncSession):
    course, _ = await make_course(db_session)
    db_session.add(make_list(course, is_published=True, visibility="public"))
    await db_session.commit()

    resp = await client.get(URL)

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_published"] is True
    citation = body["sections"][0]["citations"][0]
    assert citation["title"] == "What Is History?"
    assert citation["student_note"] == "Read chapter 1."
    assert citation["metadata"] == {}
    assert "staff_note" not in citation
    assert "INTERNAL ONLY" not in resp.text


@pytest.mark.asyncio
async def test_course_code_is_case_insensitive(client: AsyncClient, db_session: AsyncSession):
    course, _ = await make_course(db_session)
    db_session.add(make_list(course, is_published=True, visibility="public"))
    await db_session.commit()

    resp = await client.get("/api/v1/public/lists/test-org/hist101/fall-2026")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unpublished_list_hides_content(client: AsyncClient, db_session: AsyncSession):
    course, _ = await make_course(db_session)
    db_session.add(make_list(course, title="Draft list", is_published=False, visibility="public"))
    await db_session.commit()

    resp = await client.get(URL)

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_published"] is False
    assert body["title"] == "Draft list"
    assert body["sections"] == []
    assert "What Is History?" not in resp.text


@pytest.mark.asyncio
async def test_institution_only_list_is_not_public(client: AsyncClient, db_session: AsyncSession):
    course, _ = await make_course(db_session)
    db_session.add(make_list(course, is_published=True, visibility="institution"))
    await db_session.commit()

    assert (await client.get(URL)).status_code == 404


@pytest.mark.asyncio
async def test_offering_override_wins(client: AsyncClient, db_session: AsyncSession):
    course, offering = await make_course(db_session)
    db_session.add(make_list(course, title="Course default", is_published=True, visibility="public"))
    override = make_list(course, title="This term's list", is_published=True, visibility="public")
    db_session.add(override)
    await db_session.flush()  # assign ids; OfferingListOverride has FK columns, no relationships
    db_session.add(OfferingListOverride(course_offering_id=offering.id, reading_list_id=override.id))
    await db_session.commit()

    resp = await client.get(URL)
    assert resp.json()["title"] == "This term's list"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["nope/HIST101/fall-2026", "test-org/NOPE1/fall-2026", "test-org/HIST101/spring-1999"])
async def test_unknown_org_course_or_term_404s(client: AsyncClient, db_session: AsyncSession, path: str):
    course, _ = await make_course(db_session)
    db_session.add(make_list(course, is_published=True, visibility="public"))
    await db_session.commit()

    assert (await client.get(f"/api/v1/public/lists/{path}")).status_code == 404


@pytest.mark.asyncio
async def test_links_follow_the_current_discovery_settings(client: AsyncClient, db_session: AsyncSession):
    from sqlalchemy import select

    from app.models.models import LibrarySource

    course, _ = await make_course(db_session)
    reading_list = make_list(course, is_published=True, visibility="public")
    citation = reading_list.sections[0].citations[0]
    citation.source_system, citation.source_identifier = "alma", "991234567890123"
    db_session.add(reading_list)
    await db_session.commit()

    # No discovery system configured: no library link for a catalogue record
    resp = await client.get(URL)
    assert resp.json()["sections"][0]["citations"][0]["link_url"] is None

    org_id = await db_session.scalar(select(Organization.id).where(Organization.slug == "test-org"))
    source = LibrarySource(
        organization_id=org_id,
        kind="primo",
        config={"region": "na", "vid": "01TEST_INST:NDE", "discovery_url": "https://test.primo.exlibrisgroup.com"},
    )
    db_session.add(source)
    await db_session.commit()

    linked = (await client.get(URL)).json()["sections"][0]["citations"][0]
    assert linked["link_kind"] == "library_record"
    assert linked["link_url"].startswith("https://test.primo.exlibrisgroup.com/discovery/fulldisplay?docid=alma991234567890123")

    # Nothing is stored: changing the discovery settings changes every link at once
    source.config = {**source.config, "discovery_url": "https://new.primo.exlibrisgroup.com"}
    await db_session.commit()
    moved = (await client.get(URL)).json()["sections"][0]["citations"][0]
    assert moved["link_url"].startswith("https://new.primo.exlibrisgroup.com/")
