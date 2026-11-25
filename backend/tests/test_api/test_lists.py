import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Citation,
    College,
    CourseTemplate,
    Department,
    ListSection,
    Organization,
    ReadingList,
    ResourceType,
    User,
)
from app.services.auth_service import AuthService
from tests.conftest import make_org_admin


async def make_org_with_list(db: AsyncSession, slug: str, title: str) -> tuple[Organization, ReadingList]:
    org = Organization(name=slug, slug=slug)
    dept = Department(college=College(organization=org, name="Arts"), name="History")
    course = CourseTemplate(department=dept, code="HIST101", name="Methods")
    reading_list = ReadingList(course_template=course, title=title, is_published=False)
    section = ListSection(reading_list=reading_list, title="Required")
    Citation(section=section, resource_type=ResourceType.book, title="A Book", staff_note="On reserve")
    db.add(org)
    await db.flush()
    return org, reading_list


async def auth_headers(client: AsyncClient, db: AsyncSession, org: Organization) -> dict:
    email = f"staff@{org.slug}.edu"
    user = User(organization=org, email=email, display_name="Staff", password_hash=AuthService.hash_password("pw-long-enough"))
    db.add(user)
    await make_org_admin(db, user, org)
    resp = await client.post("/api/v1/auth/local/login", json={"email": email, "password": "pw-long-enough"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_lists_are_scoped_to_the_users_organization(client: AsyncClient, db_session: AsyncSession):
    org_a, list_a = await make_org_with_list(db_session, "org-a", "Org A list")
    _, list_b = await make_org_with_list(db_session, "org-b", "Org B list")
    headers = await auth_headers(client, db_session, org_a)

    resp = await client.get("/api/v1/lists", headers=headers)
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()] == ["Org A list"]

    full = await client.get(f"/api/v1/lists/{list_a.id}/full", headers=headers)
    assert full.status_code == 200
    citation = full.json()["sections"][0]["citations"][0]
    assert citation["staff_note"] == "On reserve"  # staff view includes staff notes

    other = await client.get(f"/api/v1/lists/{list_b.id}/full", headers=headers)
    assert other.status_code == 404


@pytest.mark.asyncio
async def test_lists_require_authentication(client: AsyncClient):
    assert (await client.get("/api/v1/lists")).status_code == 401
