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


class Org:
    """One organization with a list of two sections; section A has two citations."""

    async def build(self, db: AsyncSession, slug: str):
        self.org = Organization(name=slug, slug=slug)
        dept = Department(college=College(organization=self.org, name="Arts"), name="History")
        course = CourseTemplate(department=dept, code="HIST101", name="Methods")
        self.list = ReadingList(course_template=course, title="Readings", is_published=False)
        self.section_a = ListSection(reading_list=self.list, title="Required", sort_order=0)
        self.section_b = ListSection(reading_list=self.list, title="Week 1", sort_order=1)
        self.c1 = Citation(section=self.section_a, resource_type=ResourceType.book, title="One", sort_order=0)
        self.c2 = Citation(section=self.section_a, resource_type=ResourceType.book, title="Two", sort_order=1)
        db.add(self.org)
        await db.flush()
        return self


@pytest.fixture
async def setup(client: AsyncClient, db_session: AsyncSession):
    mine = await Org().build(db_session, "mine")
    theirs = await Org().build(db_session, "theirs")
    editor = User(
        organization=mine.org,
        email="ed@mine.edu",
        display_name="Editor",
        password_hash=AuthService.hash_password("long-enough-pw"),
    )
    db_session.add(editor)
    await make_org_admin(db_session, editor, mine.org)
    resp = await client.post("/api/v1/auth/local/login", json={"email": "ed@mine.edu", "password": "long-enough-pw"})
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return mine, theirs


async def full(client: AsyncClient, org: Org) -> dict:
    resp = await client.get(f"/api/v1/lists/{org.list.id}/full")
    assert resp.status_code == 200
    return resp.json()


# ── Lists ────────────────────────────────────────────────────────────────────

async def test_update_and_publish_list(client: AsyncClient, setup):
    mine, _ = setup
    resp = await client.patch(
        f"/api/v1/lists/{mine.list.id}", json={"title": "  New title ", "visibility": "unlisted"}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "New title"
    assert resp.json()["visibility"] == "unlisted"

    assert (await client.post(f"/api/v1/lists/{mine.list.id}/publish")).json()["is_published"] is True
    assert (await client.post(f"/api/v1/lists/{mine.list.id}/unpublish")).json()["is_published"] is False


@pytest.mark.parametrize("body", [{"title": ""}, {"title": None}, {"visibility": "everyone"}, {"bogus": 1}])
async def test_list_update_validation(client: AsyncClient, setup, body):
    mine, _ = setup
    assert (await client.patch(f"/api/v1/lists/{mine.list.id}", json=body)).status_code == 422


# ── Sections ─────────────────────────────────────────────────────────────────

async def test_section_create_update_reorder_delete(client: AsyncClient, setup):
    mine, _ = setup

    resp = await client.post(f"/api/v1/lists/{mine.list.id}/sections", json={"title": "Supplemental"})
    assert resp.status_code == 201
    new = resp.json()
    assert new["sort_order"] == 2

    resp = await client.patch(f"/api/v1/sections/{new['id']}", json={"description": "Optional extras"})
    assert resp.json()["description"] == "Optional extras"

    order = [new["id"], str(mine.section_b.id), str(mine.section_a.id)]
    resp = await client.post(f"/api/v1/lists/{mine.list.id}/sections/reorder", json={"section_ids": order})
    assert resp.status_code == 204
    assert [s["id"] for s in (await full(client, mine))["sections"]] == order

    assert (await client.delete(f"/api/v1/sections/{new['id']}")).status_code == 204
    assert len((await full(client, mine))["sections"]) == 2


async def test_cannot_delete_section_with_citations(client: AsyncClient, setup):
    mine, _ = setup
    resp = await client.delete(f"/api/v1/sections/{mine.section_a.id}")
    assert resp.status_code == 409
    assert "2 citation(s)" in resp.json()["detail"]


@pytest.mark.parametrize("which", ["missing_one", "duplicate", "foreign"])
async def test_reorder_must_name_every_section_once(client: AsyncClient, setup, which):
    mine, theirs = setup
    a, b = str(mine.section_a.id), str(mine.section_b.id)
    ids = {"missing_one": [a], "duplicate": [a, a, b], "foreign": [a, str(theirs.section_b.id)]}[which]
    resp = await client.post(f"/api/v1/lists/{mine.list.id}/sections/reorder", json={"section_ids": ids})
    assert resp.status_code == 422


# ── Citations ────────────────────────────────────────────────────────────────

async def test_create_citation_normalizes_input(client: AsyncClient, setup):
    mine, _ = setup
    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations",
        json={
            "resource_type": "journal_article",
            "title": "Gender: A Useful Category of Historical Analysis",
            "author": ["Scott, Joan W.", "  ", ""],
            "year": 1986,
            "doi": "https://doi.org/10.2307/1864376",
            "publisher": "",
            "staff_note": "Check access",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["doi"] == "10.2307/1864376"
    assert body["author"] == ["Scott, Joan W."]
    assert body["publisher"] is None
    assert body["staff_note"] == "Check access"
    assert body["sort_order"] == 0
    assert body["is_required"] is True
    assert body["metadata"] == {}


@pytest.mark.parametrize(
    "patch",
    [
        {"url": "javascript:alert(1)"},
        {"url": "data:text/html,hi"},
        {"doi": "not-a-doi"},
        {"year": 99999},
        {"title": ""},
        {"resource_type": "scroll"},
    ],
)
async def test_citation_validation(client: AsyncClient, setup, patch):
    mine, _ = setup
    resp = await client.patch(f"/api/v1/citations/{mine.c1.id}", json=patch)
    assert resp.status_code == 422


async def test_update_move_reorder_and_delete_citation(client: AsyncClient, setup):
    mine, _ = setup

    resp = await client.patch(
        f"/api/v1/citations/{mine.c1.id}", json={"student_note": "Read ch. 1", "is_required": False}
    )
    assert resp.status_code == 200
    assert resp.json()["student_note"] == "Read ch. 1"
    assert resp.json()["is_required"] is False

    resp = await client.patch(
        f"/api/v1/citations/{mine.c2.id}", json={"list_section_id": str(mine.section_b.id)}
    )
    assert resp.status_code == 200
    sections = (await full(client, mine))["sections"]
    assert [c["title"] for c in sections[0]["citations"]] == ["One"]
    assert [c["title"] for c in sections[1]["citations"]] == ["Two"]

    new = (
        await client.post(
            f"/api/v1/sections/{mine.section_b.id}/citations", json={"resource_type": "book", "title": "Three"}
        )
    ).json()
    order = [new["id"], str(mine.c2.id)]
    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations/reorder", json={"citation_ids": order}
    )
    assert resp.status_code == 204
    assert [c["title"] for c in (await full(client, mine))["sections"][1]["citations"]] == ["Three", "Two"]

    assert (await client.delete(f"/api/v1/citations/{new['id']}")).status_code == 204
    assert [c["title"] for c in (await full(client, mine))["sections"][1]["citations"]] == ["Two"]


async def test_cannot_move_citation_to_another_list(client: AsyncClient, db_session: AsyncSession, setup):
    mine, _ = setup
    other_list = ReadingList(course_template_id=mine.list.course_template_id, title="Other")
    other_section = ListSection(reading_list=other_list, title="S")
    db_session.add(other_list)
    await db_session.commit()

    resp = await client.patch(f"/api/v1/citations/{mine.c1.id}", json={"list_section_id": str(other_section.id)})
    assert resp.status_code == 422


# ── Organization isolation ───────────────────────────────────────────────────

async def test_other_organizations_content_is_untouchable(client: AsyncClient, setup):
    _, theirs = setup
    calls = [
        client.patch(f"/api/v1/lists/{theirs.list.id}", json={"title": "Hacked"}),
        client.post(f"/api/v1/lists/{theirs.list.id}/publish"),
        client.post(f"/api/v1/lists/{theirs.list.id}/sections", json={"title": "X"}),
        client.patch(f"/api/v1/sections/{theirs.section_b.id}", json={"title": "X"}),
        client.delete(f"/api/v1/sections/{theirs.section_b.id}"),
        client.post(f"/api/v1/sections/{theirs.section_a.id}/citations", json={"resource_type": "book", "title": "X"}),
        client.patch(f"/api/v1/citations/{theirs.c1.id}", json={"title": "X"}),
        client.delete(f"/api/v1/citations/{theirs.c1.id}"),
    ]
    for call in calls:
        assert (await call).status_code == 404


async def test_editing_requires_authentication(client: AsyncClient, setup):
    mine, _ = setup
    del client.headers["Authorization"]
    assert (await client.post(f"/api/v1/lists/{mine.list.id}/publish")).status_code == 401
