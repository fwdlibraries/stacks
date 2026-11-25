import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.models import Citation, LibrarySource, User
from app.routers.ingest import get_http_client
from app.services import credentials
from app.services.auth_service import AuthService
from tests.conftest import make_org_admin
from tests.test_api.test_list_editing import Org
from tests.test_ingest.fake_http import FakeSources
from tests.test_ingest.fixtures import CROSSREF_WORK, alma_bib

ALMA = "https://api-na.hosted.exlibrisgroup.com/almaws/v1/bibs/"
MMS = "991234567890123"


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
    db_session.add_all(
        [
            editor,
            LibrarySource(
                organization_id=mine.org.id,
                kind="alma",
                config={"region": "na"},
                api_key_encrypted=credentials.encrypt("alma-key"),
            ),
        ]
    )
    await make_org_admin(db_session, editor, mine.org)
    resp = await client.post("/api/v1/auth/local/login", json={"email": "ed@mine.edu", "password": "long-enough-pw"})
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

    fake = FakeSources()
    fake.add(ALMA + MMS, alma_bib(MMS))
    fake.add("https://api.crossref.org/works/10.1093/ahr/rhaa001", {"message": CROSSREF_WORK})

    async def fake_client():
        async with fake.client() as http:
            yield http

    app.dependency_overrides[get_http_client] = fake_client
    return mine, theirs, fake


async def add_bound(client: AsyncClient, org: Org, **extra) -> dict:
    resp = await client.post(
        f"/api/v1/sections/{org.section_b.id}/citations/from-source",
        json={"source_system": "alma", "source_identifier": MMS, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_lookup(client, setup):
    resp = await client.post("/api/v1/ingest/lookup", json={"query": f"{MMS} https://doi.org/10.1093/ahr/rhaa001"})
    assert resp.status_code == 200
    body = resp.json()
    assert [i["kind"] for i in body["identifiers"]] == ["doi", "mms_id"]
    # The library's record first, then open data
    assert [(c["source_system"], c["authoritative"]) for c in body["candidates"]] == [
        ("alma", True),
        ("crossref", False),
    ]
    assert body["candidates"][0]["citation"]["title"].startswith("What is history?")
    assert body["warnings"] == []


async def test_lookup_requires_login(client, setup):
    del client.headers["Authorization"]
    resp = await client.post("/api/v1/ingest/lookup", json={"query": MMS})
    assert resp.status_code == 401


async def test_add_from_alma_is_bound_and_uses_the_records_metadata(client, setup, db_session):
    mine, _, _ = setup
    body = await add_bound(client, mine, student_note="Read chapter 1", is_required=False)

    assert body["is_bound"] is True
    assert (body["source_system"], body["source_identifier"], body["source_status"]) == ("alma", MMS, "ok")
    assert body["source_synced_at"] is not None
    assert (body["title"], body["year"], body["isbn"]) == (
        "What is history? The George Macaulay Trevelyan lectures",
        2017,
        "9780199535569",
    )
    assert (body["student_note"], body["is_required"]) == ("Read chapter 1", False)
    stored = await db_session.scalar(select(Citation).where(Citation.id == body["id"]))
    assert stored.raw_import_data["mms_id"] == MMS


async def test_add_from_open_data_is_not_bound(client, setup):
    mine, _, _ = setup
    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations/from-source",
        json={"source_system": "crossref", "source_identifier": "10.1093/ahr/rhaa001"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert (body["is_bound"], body["source_status"], body["resource_type"]) == (False, None, "journal_article")


async def test_bound_citation_fields_are_read_only(client, setup):
    mine, _, _ = setup
    citation = await add_bound(client, mine)
    url = f"/api/v1/citations/{citation['id']}"

    resp = await client.patch(url, json={"title": "My better title"})
    assert resp.status_code == 409
    assert "Unlink" in resp.json()["detail"]

    # A form that sends everything back unchanged is fine, as are the instructor's own fields
    resp = await client.patch(
        url,
        json={"title": citation["title"], "author": citation["author"], "student_note": "Skim", "is_required": False},
    )
    assert resp.status_code == 200
    assert (resp.json()["student_note"], resp.json()["is_required"]) == ("Skim", False)


async def test_unlink_then_edit(client, setup):
    mine, _, _ = setup
    citation = await add_bound(client, mine)

    resp = await client.post(f"/api/v1/citations/{citation['id']}/unlink")
    assert resp.status_code == 200
    assert (resp.json()["is_bound"], resp.json()["source_status"]) == (False, "unlinked")
    # Provenance is kept
    assert resp.json()["source_identifier"] == MMS

    resp = await client.patch(f"/api/v1/citations/{citation['id']}", json={"title": "My better title"})
    assert resp.status_code == 200

    resp = await client.post(f"/api/v1/citations/{citation['id']}/unlink")
    assert resp.status_code == 409


async def test_record_not_found(client, setup):
    mine, _, _ = setup
    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations/from-source",
        json={"source_system": "alma", "source_identifier": "991111111110123"},
    )
    assert resp.status_code == 404


async def test_unknown_source_system(client, setup):
    mine, _, _ = setup
    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations/from-source",
        json={"source_system": "made-up", "source_identifier": "1"},
    )
    assert resp.status_code == 422


async def test_source_failure_adds_nothing(client, setup, db_session):
    mine, _, fake = setup
    fake.down.add("api-na.hosted.exlibrisgroup.com")
    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations/from-source",
        json={"source_system": "alma", "source_identifier": MMS},
    )
    assert resp.status_code == 502
    assert "Alma" in resp.json()["detail"]
    assert await db_session.scalar(select(Citation).where(Citation.source_system == "alma")) is None


async def test_alma_is_unavailable_to_orgs_without_it(client, setup):
    # "theirs" has no Alma source; its users can't import from Alma (here: the section is also not theirs)
    _, theirs, _ = setup
    resp = await client.post(
        f"/api/v1/sections/{theirs.section_b.id}/citations/from-source",
        json={"source_system": "alma", "source_identifier": MMS},
    )
    assert resp.status_code == 404


def test_credentials_round_trip():
    token = credentials.encrypt("secret-key")
    assert "secret-key" not in token
    assert credentials.decrypt(token) == "secret-key"


async def test_capabilities(client, setup):
    resp = await client.get("/api/v1/ingest/capabilities")
    # "mine" has Alma but no Primo, so no library search
    assert resp.json() == {"library_search": False}


async def test_search_needs_primo(client, setup):
    resp = await client.post("/api/v1/ingest/search", json={"query": "carbon"})
    assert resp.status_code == 409


async def test_search(client, setup, db_session):
    from tests.test_ingest.fixtures import CDI_ARTICLE
    mine, _, fake = setup
    db_session.add(
        LibrarySource(
            organization_id=mine.org.id,
            kind="primo",
            config={"region": "na", "vid": "01ABC_INST:MAIN", "discovery_url": "https://abc.primo.exlibrisgroup.com"},
            api_key_encrypted=credentials.encrypt("primo-key"),
        )
    )
    await db_session.commit()
    fake.add("https://api-na.hosted.exlibrisgroup.com/primo/v1/search", {"info": {"total": 1}, "docs": [CDI_ARTICLE]})

    assert (await client.get("/api/v1/ingest/capabilities")).json() == {"library_search": True}
    resp = await client.post("/api/v1/ingest/search", json={"query": "carbon", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    [candidate] = body["candidates"]
    assert (candidate["source_system"], candidate["availability"]) == ("primo", "online")

    resp = await client.post(
        f"/api/v1/sections/{mine.section_b.id}/citations/from-source",
        json={"source_system": "primo", "source_identifier": candidate["source_identifier"]},
    )
    assert resp.status_code == 201
    assert (resp.json()["is_bound"], resp.json()["doi"]) == (False, "10.1016/j.enpol.2007.02.016")


async def test_staff_list_includes_live_links(client, setup):
    mine, _, _ = setup
    citation = await add_bound(client, mine)
    # "mine" has no Primo source, so the bound record has no library link; its ISBN has no resolver either
    full = (await client.get(f"/api/v1/lists/{mine.list.id}/full")).json()
    [added] = [c for s in full["sections"] for c in s["citations"] if c["id"] == citation["id"]]
    assert (added["link_url"], added["link_kind"]) == (None, None)


async def test_history_lists_sync_events(client, setup, db_session):
    from app.models.models import CitationEvent
    mine, _, _ = setup
    citation = await add_bound(client, mine)
    db_session.add(CitationEvent(citation_id=citation["id"], kind="updated", source_system="alma", details={"year": [1999, 2017]}))
    await db_session.commit()
    body = (await client.get(f"/api/v1/citations/{citation['id']}/history")).json()
    assert [(e["kind"], e["details"]) for e in body] == [("updated", {"year": [1999, 2017]})]
