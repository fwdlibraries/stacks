import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.models import Citation, LibrarySource, LinkClick, ResourceType
from app.routers.ingest import get_http_client
from app.services.ephemeral import MemoryStore, get_ephemeral_store
from tests.test_api.test_list_editing import setup  # noqa: F401  (fixture)
from tests.test_resolution import ALMA, Router, cto

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def go_env(client: AsyncClient, db_session: AsyncSession, setup):  # noqa: F811
    mine, theirs = setup
    db_session.add(
        LibrarySource(
            organization_id=mine.org.id,
            kind="primo",
            config={"region": "na", "vid": "01ABC_INST:NDE", "discovery_url": "https://abc.primo.exlibrisgroup.com"},
        )
    )
    article = Citation(
        section=mine.section_b,
        resource_type=ResourceType.journal_article,
        title="Article",
        sort_order=0,
        doi="10.1/x",
        issn="1234-5678",
    )
    db_session.add(article)
    mine.list.is_published = True
    mine.org.link_resolver_settings = {"stack": ["alma"]}
    await db_session.commit()

    router = Router()
    router.xml[ALMA] = cto({"keys": {"package_public_name": "JSTOR"}, "url": "https://alma/jstor"})
    store = MemoryStore()

    async def fake_client():
        async with router.client() as http:
            yield http

    app.dependency_overrides[get_http_client] = fake_client
    app.dependency_overrides[get_ephemeral_store] = lambda: store
    return mine, article, router


async def clicks(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(LinkClick))


async def test_go_redirects_to_the_resource_and_counts_the_click(client, db_session, go_env):
    _, article, router = go_env
    resp = await client.get(f"/api/v1/go/{article.id}", headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://alma/jstor"
    assert resp.headers["cache-control"] == "no-store"
    assert await clicks(db_session) == 1
    assert (await db_session.scalar(select(LinkClick.resolved_by))) == "alma"

    # Cached: a second click doesn't ask Alma again, but still counts
    await client.get(f"/api/v1/go/{article.id}", headers={"User-Agent": "Mozilla/5.0"})
    assert len(router.requests) == 1
    assert await clicks(db_session) == 2


@pytest.mark.parametrize(
    ("params", "agent"),
    [({"preview": "true"}, "Mozilla/5.0"), ({}, "Slackbot-LinkExpanding 1.0"), ({}, "Mozilla/5.0 (compatible; Googlebot/2.1)")],
)
async def test_previews_and_bots_are_not_counted(client, db_session, go_env, params, agent):
    _, article, _ = go_env
    resp = await client.get(f"/api/v1/go/{article.id}", params=params, headers={"User-Agent": agent})
    assert resp.status_code == 302
    assert await clicks(db_session) == 0


async def test_unpublished_list_clicks_are_not_counted(client, db_session, go_env):
    mine, article, _ = go_env
    mine.list.is_published = False
    await db_session.commit()
    resp = await client.get(f"/api/v1/go/{article.id}", headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 302
    assert await clicks(db_session) == 0


async def test_unknown_citation(client, go_env):
    resp = await client.get("/api/v1/go/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_list_links_point_at_go(client, go_env):
    mine, article, _ = go_env
    full = (await client.get(f"/api/v1/lists/{mine.list.id}/full")).json()
    [linked] = [c for s in full["sections"] for c in s["citations"] if c["id"] == str(article.id)]
    assert (linked["link_url"], linked["link_kind"]) == (f"/api/v1/go/{article.id}", "full_text")


async def test_link_check_reports_each_step(client, go_env):
    _, article, _ = go_env
    body = (await client.get(f"/api/v1/citations/{article.id}/link-check")).json()
    assert (body["url"], body["resolved_by"], body["detail"], body["retracted"]) == ("https://alma/jstor", "alma", "JSTOR", False)
    assert [(s["step"], s["outcome"]) for s in body["steps"]] == [("alma", "found")]


async def test_click_stats_for_instructors(client, db_session, go_env):
    mine, article, _ = go_env
    for _ in range(3):
        await client.get(f"/api/v1/go/{article.id}", headers={"User-Agent": "Mozilla/5.0"})
    body = (await client.get(f"/api/v1/lists/{mine.list.id}/clicks")).json()
    assert body == {"citations": {str(article.id): {"total": 3, "last_30_days": 3}}}


async def test_click_stats_are_org_scoped(client, go_env, setup):  # noqa: F811
    _, theirs = setup
    assert (await client.get(f"/api/v1/lists/{theirs.list.id}/clicks")).status_code == 404


async def test_deleting_a_citation_deletes_its_clicks(client, db_session, go_env):
    _, article, _ = go_env
    await client.get(f"/api/v1/go/{article.id}", headers={"User-Agent": "Mozilla/5.0"})
    assert (await client.delete(f"/api/v1/citations/{article.id}")).status_code == 204
    assert await clicks(db_session) == 0
