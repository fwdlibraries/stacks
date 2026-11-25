import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.models import ApiKey, Citation
from app.routers.ingest import get_http_client
from tests.test_api.test_list_editing import setup  # noqa: F401  (fixture)
from tests.test_ingest.fake_http import FakeSources

pytestmark = pytest.mark.asyncio

ARTICLE_PAGE = {
    "url": "https://www.example-journal.org/doi/full/10.2307/1864376",
    "title": "Gender | AHR",
    "meta": {
        "citation_title": ["Gender: A Useful Category of Historical Analysis"],
        "citation_author": ["Scott, Joan W."],
        "citation_journal_title": ["The American Historical Review"],
        "citation_date": ["1986"],
    },
    "jsonld": [],
}


@pytest.fixture
async def ext(client: AsyncClient, db_session: AsyncSession, setup):  # noqa: F811
    mine, theirs = setup
    fake = FakeSources()
    fake.add("https://api.crossref.org/works/10.2307/1864376", {"message": {
        "DOI": "10.2307/1864376", "type": "journal-article", "title": ["Gender: A Useful Category of Historical Analysis"],
        "author": [{"family": "Scott", "given": "Joan W."}], "issued": {"date-parts": [[1986]]},
        "container-title": ["The American Historical Review"]}})

    async def fake_client():
        async with fake.client() as http:
            yield http

    app.dependency_overrides[get_http_client] = fake_client
    resp = await client.post("/api/v1/extension/tokens", json={"browser": "Firefox"})
    assert resp.status_code == 201
    session = client.headers["Authorization"]
    return mine, theirs, resp.json(), session


def as_extension(client: AsyncClient, token: str) -> None:
    client.headers["Authorization"] = f"Bearer {token}"


async def test_token_is_stored_hashed_and_shown_once(client, db_session, ext):
    _, _, created, _ = ext
    assert created["token"].startswith("stx_") and created["name"] == "Browser extension (Firefox)"
    key = await db_session.scalar(select(ApiKey))
    assert created["token"] not in (key.key_hash, key.key_prefix) and key.scopes == ["extension"]
    listed = (await client.get("/api/v1/extension/tokens")).json()
    assert [t["id"] for t in listed] == [created["id"]] and "token" not in listed[0]


async def test_extension_flow(client, db_session, ext):
    mine, theirs, created, _ = ext
    as_extension(client, created["token"])

    me = (await client.get("/api/v1/extension/me")).json()
    assert me == {"display_name": "Editor", "organization": "mine"}
    targets = (await client.get("/api/v1/extension/targets")).json()
    assert [t["id"] for t in targets] == [str(mine.list.id)]  # only my organization's lists
    assert [s["title"] for s in targets[0]["sections"]] == ["Required", "Week 1"]

    page = (await client.post("/api/v1/ingest/page", json=ARTICLE_PAGE)).json()
    assert page["page"]["doi"] == "10.2307/1864376"  # from the URL
    assert page["page"]["url"] == ARTICLE_PAGE["url"]
    [match] = page["candidates"]
    assert (match["source_system"], match["source_identifier"]) == ("crossref", "10.2307/1864376")

    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations/from-source",
        json={"source_system": "crossref", "source_identifier": "10.2307/1864376", "student_note": "Read all"},
    )
    assert resp.status_code == 201
    # Or the page as entered
    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations",
        json={"resource_type": "website", "title": "A guide", "url": "https://example.org/guide"},
    )
    assert resp.status_code == 201
    titles = set(await db_session.scalars(select(Citation.title).where(Citation.list_section_id == mine.section_b.id)))
    assert {"Gender: A Useful Category of Historical Analysis", "A guide"} <= titles

    # Another organization's section is still off limits
    resp = await client.post(
        f"/api/v1/sections/{theirs.section_b.id}/citations",
        json={"resource_type": "website", "title": "x", "url": "https://example.org"},
    )
    assert resp.status_code == 404


async def test_ordinary_pages_are_not_searched(client, ext):
    _, _, created, _ = ext
    as_extension(client, created["token"])
    page = (await client.post("/api/v1/ingest/page", json={"url": "https://example.org/blog", "title": "My blog post"})).json()
    assert (page["page"]["resource_type"], page["candidates"]) == ("website", [])


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/lists"),
        ("get", "/api/v1/extension/tokens"),
        ("post", "/api/v1/extension/tokens"),
        ("get", "/api/v1/auth/me"),
    ],
)
async def test_extension_token_only_opens_extension_endpoints(client, ext, method, path):
    _, _, created, _ = ext
    as_extension(client, created["token"])
    resp = await getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert resp.status_code == 401


async def test_revoked_token_stops_working(client, ext):
    _, _, created, session = ext
    assert (await client.delete(f"/api/v1/extension/tokens/{created['id']}")).status_code == 204
    as_extension(client, created["token"])
    assert (await client.get("/api/v1/extension/me")).status_code == 401
    client.headers["Authorization"] = session
    assert (await client.get("/api/v1/extension/tokens")).json() == []


async def test_made_up_token(client, ext):
    as_extension(client, "stx_not-a-real-token")
    assert (await client.get("/api/v1/extension/targets")).status_code == 401
