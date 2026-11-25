"""Role scopes: who sees and changes which reading lists."""
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
    Organization,
    ReadingList,
    ResourceType,
    ScopeType,
    User,
)
from app.services import access
from app.services.auth_service import AuthService

pytestmark = pytest.mark.asyncio
PASSWORD = "long-enough-pw"


class World:
    """One organization: Arts (History: HIST101, HIST202) and Science (Biology: BIO101)."""

    async def build(self, db: AsyncSession):
        self.org = Organization(name="Uni", slug="uni")
        self.arts = College(organization=self.org, name="Arts", code="ARTS")
        self.science = College(organization=self.org, name="Science", code="SCI")
        self.history = Department(college=self.arts, name="History", code="HIST")
        self.biology = Department(college=self.science, name="Biology", code="BIO")
        self.lists = {}
        for dept, code in ((self.history, "HIST101"), (self.history, "HIST202"), (self.biology, "BIO101")):
            course = CourseTemplate(department=dept, code=code, name=code)
            reading_list = ReadingList(course_template=course, title=f"{code} list", is_published=True)
            section = ListSection(reading_list=reading_list, title="Required", sort_order=0)
            Citation(section=section, resource_type=ResourceType.book, title=f"{code} book", sort_order=0)
            self.lists[code] = reading_list
            if code == "HIST101":
                self.hist101_fall = CourseOffering(template=course, term="fall-2026")
        db.add(self.org)
        await db.flush()
        return self

    async def person(self, db: AsyncSession, name: str, role: str | None = None, scope=None) -> User:
        user = User(organization=self.org, email=f"{name}@uni.edu", display_name=name,
                    password_hash=AuthService.hash_password(PASSWORD))
        db.add(user)
        await db.flush()
        if role:
            await access.grant(db, user, role, *scope)
        await db.commit()
        return user


@pytest.fixture
async def world(db_session: AsyncSession):
    return await World().build(db_session)


async def sign_in(client: AsyncClient, user: User) -> None:
    client.headers.pop("Authorization", None)
    resp = await client.post("/api/v1/auth/local/login", json={"email": user.email, "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"


async def visible(client: AsyncClient) -> dict[str, tuple[bool, bool]]:
    return {item["title"]: (item["can_edit"], item["can_publish"]) for item in (await client.get("/api/v1/lists")).json()}


async def add_citation(client: AsyncClient, reading_list: ReadingList):
    full = (await client.get(f"/api/v1/lists/{reading_list.id}/full")).json()
    section_id = full["sections"][0]["id"]
    return await client.post(f"/api/v1/sections/{section_id}/citations", json={"resource_type": "book", "title": "New"})


async def test_department_librarian(client, db_session, world):
    user = await world.person(db_session, "lib", access.LIBRARIAN, (ScopeType.department, world.history.id))
    await sign_in(client, user)
    assert await visible(client) == {"HIST101 list": (True, True), "HIST202 list": (True, True)}
    assert (await add_citation(client, world.lists["HIST202"])).status_code == 201
    # Another department's list doesn't exist as far as they can tell
    assert (await client.get(f"/api/v1/lists/{world.lists['BIO101'].id}/full")).status_code == 404


async def test_instructor_of_one_offering(client, db_session, world):
    user = await world.person(db_session, "ins", access.INSTRUCTOR, (ScopeType.course_offering, world.hist101_fall.id))
    await sign_in(client, user)
    assert await visible(client) == {"HIST101 list": (True, True)}
    assert (await add_citation(client, world.lists["HIST101"])).status_code == 201
    assert (await client.patch(f"/api/v1/lists/{world.lists['HIST202'].id}", json={"title": "x"})).status_code == 404


async def test_viewer_sees_but_cannot_change(client, db_session, world):
    user = await world.person(db_session, "view", access.VIEWER, (ScopeType.organization, world.org.id))
    await sign_in(client, user)
    assert await visible(client) == {f"{c} list": (False, False) for c in ("HIST101", "HIST202", "BIO101")}
    hist = world.lists["HIST101"]
    full = await client.get(f"/api/v1/lists/{hist.id}/full")
    assert (full.status_code, full.json()["can_edit"]) == (200, False)
    section_id = full.json()["sections"][0]["id"]
    citation_id = full.json()["sections"][0]["citations"][0]["id"]

    refused = [
        await client.patch(f"/api/v1/lists/{hist.id}", json={"title": "x"}),
        await client.patch(f"/api/v1/lists/{hist.id}", json={"visibility": "unlisted"}),
        await client.post(f"/api/v1/lists/{hist.id}/unpublish"),
        await client.post(f"/api/v1/lists/{hist.id}/sections", json={"title": "x"}),
        await client.post(f"/api/v1/sections/{section_id}/citations", json={"resource_type": "book", "title": "x"}),
        await client.patch(f"/api/v1/citations/{citation_id}", json={"title": "x"}),
        await client.delete(f"/api/v1/citations/{citation_id}"),
        await client.post(f"/api/v1/lists/{hist.id}/imports", json={"text": "Carr. What is history? 1961.", "section_id": section_id}),
        await client.post("/api/v1/ingest/lookup", json={"query": "10.1000/x"}),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert "permission" in refused[0].json()["detail"]
    # Viewing what's there is fine
    assert (await client.get(f"/api/v1/citations/{citation_id}/history")).status_code == 200
    assert (await client.get(f"/api/v1/lists/{hist.id}/clicks")).status_code == 200


async def test_no_roles_no_lists(client, db_session, world):
    user = await world.person(db_session, "nobody")
    await sign_in(client, user)
    assert await visible(client) == {}
    assert (await client.get(f"/api/v1/lists/{world.lists['HIST101'].id}/full")).status_code == 404
    assert (await client.get("/api/v1/extension/targets")).json() == []


async def test_college_admin_manages_their_college_but_not_org_settings(db_session, world):
    college_admin = await world.person(db_session, "cadm", access.ADMINISTRATOR, (ScopeType.college, world.arts.id))
    org_admin = await world.person(db_session, "oadm", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    college = await access.load_grants(db_session, college_admin)
    assert college.anywhere("people.manage") and college.anywhere("lists.edit")
    assert not college.organization_wide("settings.manage")
    assert not college.anywhere("settings.manage")  # organization-only, even though the role has it
    assert (await access.load_grants(db_session, org_admin)).organization_wide("settings.manage")


async def test_system_admin_bypasses(client, db_session, world):
    user = await world.person(db_session, "sys")
    user.is_system_admin = True
    await db_session.commit()
    await sign_in(client, user)
    assert len(await visible(client)) == 3


async def test_grants_are_idempotent_and_catalog_is_stable(db_session, world):
    user = await world.person(db_session, "twice")
    first = await access.grant(db_session, user, access.LIBRARIAN, ScopeType.department, world.history.id)
    again = await access.grant(db_session, user, access.LIBRARIAN, ScopeType.department, world.history.id)
    assert first.id == again.id
    roles = await access.ensure_catalog(db_session)
    assert set(roles) == {"Administrator", "Librarian", "Instructor", "Viewer"}
    assert set(access.PERMISSIONS) >= {"lists.view", "lists.edit", "lists.publish", "settings.manage"}
