import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest import bulk
from app.ingest.resolvers import ResolveContext
from app.main import app
from app.models.models import Citation, LibrarySource
from app.routers import imports
from app.routers.ingest import get_http_client
from app.services import credentials
from tests.test_api.test_list_editing import setup  # noqa: F401  (fixture)
from tests.test_ingest.fake_http import FakeSources
from tests.test_ingest.fixtures import alma_bib, primo_search_doc
from tests.test_ingest.test_pipeline import LIBRARY

pytestmark = pytest.mark.asyncio

PRIMO = "https://api-na.hosted.exlibrisgroup.com/primo/v1/search"
BIBS = "https://api-na.hosted.exlibrisgroup.com/almaws/v1/bibs"
CROSSREF = "https://api.crossref.org/works"
MMS = "991000000000013687"

TEXT = """1. Carr, E. H. (1961). What is history? The George Macaulay Trevelyan lectures. London: Macmillan.
2. Nobody, N. (2019). An article that matches nothing at all. Journal of Nothing, 3, 1-2.
3. Scott, J. W. (1986). Gender. https://doi.org/10.2307/1864376
"""


@pytest.fixture
async def env(client: AsyncClient, db_session: AsyncSession, setup, monkeypatch):  # noqa: F811
    mine, theirs = setup
    for kind, config in (("alma", {"region": "na"}), ("primo", {**LIBRARY["primo"].config.model_dump()})):
        db_session.add(
            LibrarySource(organization_id=mine.org.id, kind=kind, config=config, api_key_encrypted=credentials.encrypt("k"))
        )
    await db_session.commit()

    fake = FakeSources()
    fake.add(PRIMO, {"info": {"total": 1}, "docs": [primo_search_doc(f"alma{MMS}", context="L", title="What is history? : the George Macaulay Trevelyan lectures",
                                                                      creator=["Carr, Edward Hallett"], addata={"date": ["1961"]})]})
    fake.add(BIBS, {"bib": [alma_bib(MMS)]})
    fake.add(CROSSREF, {"message": {"items": []}})
    fake.add(f"{CROSSREF}/10.2307/1864376", {"message": {"DOI": "10.2307/1864376", "type": "journal-article",
                                                           "title": ["Gender: A Useful Category of Historical Analysis"],
                                                           "author": [{"family": "Scott", "given": "Joan W."}],
                                                           "issued": {"date-parts": [[1986]]}}})

    async def fake_client():
        async with fake.client() as http:
            yield http

    app.dependency_overrides[get_http_client] = fake_client
    queued: list[str] = []
    monkeypatch.setattr(imports, "enqueue_matching", queued.append)
    return mine, theirs, fake, queued


async def start(client, org, text=TEXT):
    return await client.post(f"/api/v1/lists/{org.list.id}/imports", json={"text": text, "section_id": str(org.section_b.id)})


async def match_now(db_session, job_id, fake):
    from app.ingest.sources import load_sources
    from app.models.models import BackgroundJob

    job = await db_session.get(BackgroundJob, job_id)
    async with fake.client() as http:
        sources = await load_sources(db_session, __import__("uuid").UUID(job.payload["organization_id"]))
        await bulk.run_matching(db_session, job.id, ResolveContext(http=http, sources=sources))


async def test_import_review_and_add(client, db_session, env):
    mine, _, fake, queued = env
    resp = await start(client, mine)
    assert resp.status_code == 202
    job = resp.json()
    assert (job["status"], job["total"], queued) == ("queued", 3, [job["id"]])

    await match_now(db_session, job["id"], fake)
    review = (await client.get(f"/api/v1/imports/{job['id']}")).json()
    assert (review["status"], review["matched"]) == ("awaiting_review", 3)
    carr, nothing, scott = review["items"]
    assert carr["candidates"][0]["source_system"] == "alma"
    assert carr["candidates"][0]["confidence"] >= review["good_match"]
    assert nothing["candidates"] == []
    assert scott["candidates"][0]["source_system"] == "crossref"  # matched by DOI

    resp = await client.post(
        f"/api/v1/imports/{job['id']}/add",
        json={"items": [
            {"id": carr["id"], "choice": "match", "candidate_index": 0},
            {"id": nothing["id"], "choice": "as_entered"},
            {"id": scott["id"], "choice": "skip"},
        ]},
    )
    assert resp.json() == {"added": 2, "skipped": 1, "failed": []}

    added = list(await db_session.scalars(
        select(Citation).where(Citation.list_section_id == mine.section_b.id).order_by(Citation.sort_order)
        .execution_options(populate_existing=True)
    ))
    bound, entered = added
    # The library record comes from Alma's full record, bound and kept in sync
    assert (bound.source_system, bound.source_identifier, bound.source_status) == ("alma", MMS, "ok")
    assert bound.title == "What is history? The George Macaulay Trevelyan lectures"
    assert (bound.match_method, bound.match_confidence) == ("search", carr["candidates"][0]["confidence"])
    # Nothing matched: best-guess title, the full reference kept
    assert entered.title == "An article that matches nothing at all"
    assert entered.metadata_["original_reference"].startswith("Nobody, N. (2019)")
    assert (entered.source_system, entered.year) == ("import", 2019)

    # Added once only
    again = await client.post(f"/api/v1/imports/{job['id']}/add", json={"items": []})
    assert again.status_code == 409


async def test_add_before_matching_finishes(client, env):
    mine, _, _, _ = env
    job = (await start(client, mine)).json()
    assert (await client.post(f"/api/v1/imports/{job['id']}/add", json={"items": []})).status_code == 409


async def test_imports_are_org_scoped(client, env):
    mine, theirs, _, _ = env
    other_section = await client.post(
        f"/api/v1/lists/{theirs.list.id}/imports", json={"text": TEXT, "section_id": str(theirs.section_b.id)}
    )
    assert other_section.status_code == 404
    # A section from another list of mine isn't accepted either
    bad = await client.post(f"/api/v1/lists/{mine.list.id}/imports", json={"text": TEXT, "section_id": str(theirs.section_b.id)})
    assert bad.status_code == 404


async def test_nothing_to_import(client, env):
    mine, _, _, queued = env
    resp = await start(client, mine, text="   short   ")
    assert resp.status_code == 422
    assert queued == []
