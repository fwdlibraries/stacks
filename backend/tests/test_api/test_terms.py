"""Rollover stage 1: terms, section lists, copying lists between terms, LMS section codes."""
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Citation,
    CourseOffering,
    ListSection,
    Organization,
    ReadingList,
    ScopeType,
    Term,
)
from app.services import access, terms
from tests.test_api.test_lti import exchange, launch, platform, store  # noqa: F401 (fixtures)
from tests.test_api.test_permissions import World, sign_in

# ── Section code patterns ────────────────────────────────────────────────────


def test_section_code_pattern():
    parsed = terms.parse_section_code("{crn}.{term}", "40112.202710")
    assert (parsed.crn, parsed.term) == ("40112", "202710")
    assert terms.parse_section_code("{crn}.{term}", "GEO101_OL_TER_PRIMARY") is None
    assert terms.parse_section_code("{course}-{section}-{term}", "GEO 101-02-F27").course == "GEO 101"
    assert terms.parse_section_code(None, "40112.202710") is None


@pytest.mark.parametrize(
    "pattern,message",
    [("{crn}", "needs {term}"), ("{crn}.{term}.{nope}", "Unknown placeholder {nope}"), ("{term}{term}", "once")],
)
def test_bad_patterns(pattern, message):
    with pytest.raises(terms.PatternError, match=message.replace("{", r"\{").replace("}", r"\}")):
        terms.compile_pattern(pattern)


# ── Copying lists ────────────────────────────────────────────────────────────


@pytest.fixture
async def world(db_session: AsyncSession):
    world = await World().build(db_session)
    world.spring = Term(organization_id=world.org.id, code="spring-2027", name="Spring 2027")
    db_session.add(world.spring)
    await db_session.commit()
    return world


async def copy(client: AsyncClient, reading_list: ReadingList, term: Term, **extra):
    return await client.post(f"/api/v1/lists/{reading_list.id}/copy", json={"term_id": str(term.id), **extra})


async def test_copy_makes_a_draft_section_list_with_the_same_item_keys(client, db_session, world):
    admin = await world.person(db_session, "admin", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    await sign_in(client, admin)
    source = world.lists["HIST101"]

    resp = await copy(client, source, world.spring)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "section" and body["is_published"] is False
    assert body["term"] == {"code": "spring-2027", "name": "Spring 2027"}
    assert body["copied_from"]["id"] == str(source.id) and body["copied_from"]["kind"] == "course"

    new_citation = await db_session.scalar(
        select(Citation).join(ListSection).where(ListSection.reading_list_id == body["id"])
    )
    old_citation = await db_session.scalar(
        select(Citation).join(ListSection).where(ListSection.reading_list_id == source.id)
    )
    assert new_citation.id != old_citation.id
    assert (new_citation.item_key, new_citation.title) == (old_citation.item_key, old_citation.title)

    # The term now has its own list; copying into it again is refused
    again = await copy(client, source, world.spring)
    assert again.status_code == 409 and again.json()["detail"]["list_id"] == body["id"]


async def test_each_term_shows_its_own_list(client, db_session, world):
    admin = await world.person(db_session, "admin", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    await sign_in(client, admin)
    copied = (await copy(client, world.lists["HIST101"], world.spring)).json()
    await client.patch(f"/api/v1/lists/{copied['id']}", json={"title": "Spring readings"})
    await client.post(f"/api/v1/lists/{copied['id']}/publish")

    client.headers.pop("Authorization")
    spring = await client.get("/api/v1/public/lists/uni/HIST101/spring-2027")
    fall = await client.get("/api/v1/public/lists/uni/HIST101/fall-2026")
    assert spring.json()["title"] == "Spring readings"
    assert fall.json()["title"] == "HIST101 list"  # the shared course list, unchanged


async def test_instructors_see_their_own_term_only_and_cannot_copy(client, db_session, world):
    admin = await world.person(db_session, "admin", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    await sign_in(client, admin)
    spring_list = (await copy(client, world.lists["HIST101"], world.spring)).json()

    fall_instructor = await world.person(
        db_session, "ins", access.INSTRUCTOR, (ScopeType.course_offering, world.hist101_fall.id)
    )
    await sign_in(client, fall_instructor)
    titles = [item["title"] for item in (await client.get("/api/v1/lists")).json()]
    assert titles == ["HIST101 list"]  # not Spring's section list
    assert (await client.get("/api/v1/lists")).json()[0]["can_copy"] is False
    assert (await client.get(f"/api/v1/lists/{spring_list['id']}/full")).status_code == 404
    # Making lists for other terms needs the whole course, not one offering
    assert (await copy(client, world.lists["HIST101"], world.spring, section="02")).status_code == 403


async def test_department_librarian_can_copy_into_a_section(client, db_session, world):
    librarian = await world.person(db_session, "lib", access.LIBRARIAN, (ScopeType.department, world.history.id))
    await sign_in(client, librarian)
    assert all(item["can_copy"] for item in (await client.get("/api/v1/lists")).json())
    resp = await copy(client, world.lists["HIST202"], world.spring, section="40112")
    assert resp.status_code == 201
    assert resp.json()["section"] == "40112"
    offering = await db_session.scalar(select(CourseOffering).where(CourseOffering.section == "40112"))
    assert offering.term_id == world.spring.id
    # Not into another organization's term
    other = Organization(name="Other", slug="other")
    db_session.add(other)
    await db_session.flush()
    elsewhere = Term(organization_id=other.id, code="x", name="X")
    db_session.add(elsewhere)
    await db_session.commit()
    assert (await copy(client, world.lists["HIST202"], elsewhere)).status_code == 404


# ── LMS launches ─────────────────────────────────────────────────────────────


async def test_launch_reads_the_term_from_the_section_code(client, db_session, platform, store):  # noqa: F811
    org = await db_session.get(Organization, platform.organization_id)
    org.settings = {"section_code_pattern": "{crn}.{term}"}
    await db_session.commit()

    await exchange(
        client, await launch(client, context={"id": "ctx-9", "label": "40112.202710", "title": "GEO 101"}, custom={})
    )
    offering = await db_session.scalar(select(CourseOffering))
    assert (offering.term, offering.section, offering.lms_code) == ("202710", "40112", "40112.202710")
    term = await db_session.get(Term, offering.term_id)
    assert (term.code, term.name) == ("202710", "202710")


async def test_launch_finds_an_offering_made_ahead_by_its_exact_code(client, db_session, platform, store):  # noqa: F811
    # First term: the course and its shared list come from a normal launch
    first = await exchange(client, await launch(client))
    offering = await db_session.scalar(select(CourseOffering))
    # Made ahead of term (as rollover will) for a shell coded differently from the course
    ahead = CourseOffering(course_template_id=offering.course_template_id, term="spring-2027", lms_code="SHELL-77")
    db_session.add(ahead)
    await db_session.commit()

    second = await exchange(
        client,
        await launch(
            client,
            context={"id": "ctx-77", "label": "shell-77", "title": "Something else"},
            custom={"term": "Spring 2027"},
        ),
    )
    assert second["next"] == first["next"]  # same course list (no section list yet)
    assert await db_session.scalar(select(func.count()).select_from(CourseOffering)) == 2
    await db_session.refresh(ahead)
    assert ahead.lti_context_id is None  # matched through the context mapping
    from app.models.models import LtiContextMapping

    mapping = await db_session.scalar(select(LtiContextMapping).where(LtiContextMapping.lti_context_id == "ctx-77"))
    assert mapping.course_offering_id == ahead.id


# ── Administration › Terms ───────────────────────────────────────────────────


async def test_terms_admin(client, db_session, world):
    admin = await world.person(db_session, "admin", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    await sign_in(client, admin)

    resp = await client.post(
        "/api/v1/admin/terms",
        json={"code": " 202710 ", "name": "Fall 2027", "starts_on": "2027-08-30", "ends_on": "2027-12-17"},
    )
    assert resp.status_code == 201, resp.text
    fall = next(t for t in resp.json()["terms"] if t["code"] == "202710")
    assert fall["name"] == "Fall 2027" and fall["offerings"] == 0

    assert (await client.post("/api/v1/admin/terms", json={"code": "202710", "name": "Dup"})).status_code == 409
    bad = await client.post(
        "/api/v1/admin/terms", json={"code": "x", "name": "x", "starts_on": "2027-02-01", "ends_on": "2027-01-01"}
    )
    assert bad.status_code == 422

    # A term courses use keeps its code, and can't be removed
    copied = await copy(client, world.lists["HIST101"], world.spring)
    assert copied.status_code == 201
    change = await client.put(f"/api/v1/admin/terms/{world.spring.id}", json={"code": "sp27", "name": "Spring 2027"})
    assert change.status_code == 409
    rename = await client.put(f"/api/v1/admin/terms/{world.spring.id}", json={"code": "spring-2027", "name": "Spring ’27"})
    assert rename.status_code == 200
    assert (await client.delete(f"/api/v1/admin/terms/{world.spring.id}")).status_code == 409
    assert (await client.delete(f"/api/v1/admin/terms/{fall['id']}")).status_code == 204


async def test_section_code_pattern_admin(client, db_session, world):
    admin = await world.person(db_session, "admin", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    await sign_in(client, admin)

    assert (await client.put("/api/v1/admin/terms-pattern", json={"section_code_pattern": "{crn}"})).status_code == 422
    saved = await client.put("/api/v1/admin/terms-pattern", json={"section_code_pattern": "{crn}.{term}"})
    assert saved.json()["section_code_pattern"] == "{crn}.{term}"
    # Saving it keeps the organization's other settings
    await db_session.refresh(world.org)
    assert world.org.settings["section_code_pattern"] == "{crn}.{term}"

    tried = (await client.post("/api/v1/admin/terms-pattern/try", json={"code": "40112.spring-2027"})).json()
    assert tried == {
        "matches": True, "error": None, "term": "spring-2027", "term_name": "Spring 2027",
        "crn": "40112", "section": None, "course": None,
    }
    assert (await client.post("/api/v1/admin/terms-pattern/try", json={"code": "nope"})).json()["matches"] is False


async def test_terms_admin_needs_settings_permission(client, db_session, world):
    librarian = await world.person(db_session, "lib", access.LIBRARIAN, (ScopeType.department, world.history.id))
    await sign_in(client, librarian)
    assert (await client.get("/api/v1/admin/terms")).status_code == 403
    # Staff can still list terms to copy into
    assert [t["code"] for t in (await client.get("/api/v1/terms")).json()] == ["spring-2027"]
