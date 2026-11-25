"""Organization administration API."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.models.models import College, LibrarySource, Organization, ScopeType, User
from app.routers.ingest import get_http_client
from app.services import access, credentials
from app.services.auth_service import AuthService
from tests.test_ingest.fake_http import FakeSources

PASSWORD = "long-enough-pw"


@pytest.fixture
async def org(db_session: AsyncSession):
    org = Organization(name="Uni", slug="uni")
    college = College(organization=org, name="Arts", code="ARTS")
    db_session.add_all([org, college])
    await db_session.flush()
    return org, college


async def person(db, org, name, role=None, scope=None, system=False) -> User:
    user = User(organization=org, email=f"{name}@uni.edu", display_name=name, is_system_admin=system,
                password_hash=AuthService.hash_password(PASSWORD))
    db.add(user)
    await db.flush()
    if role:
        await access.grant(db, user, role, *scope)
    await db.commit()
    return user


async def sign_in(client: AsyncClient, user: User):
    client.headers.pop("Authorization", None)
    token = (await client.post("/api/v1/auth/local/login", json={"email": user.email, "password": PASSWORD})).json()
    client.headers["Authorization"] = f"Bearer {token['access_token']}"


@pytest.fixture
async def admin(client, db_session, org):
    the_org, _ = org
    user = await person(db_session, the_org, "admin", access.ADMINISTRATOR, (ScopeType.organization, the_org.id))
    await sign_in(client, user)
    return user


async def test_only_organization_wide_admins(client, db_session, org):
    the_org, college = org
    for name, role, scope in (
        ("cadm", access.ADMINISTRATOR, (ScopeType.college, college.id)),
        ("lib", access.LIBRARIAN, (ScopeType.organization, the_org.id)),
    ):
        await sign_in(client, await person(db_session, the_org, name, role, scope))
        for path in ("/api/v1/admin/organization", "/api/v1/admin/sources", "/api/v1/admin/link-resolution"):
            assert (await client.get(path)).status_code == 403, (name, path)
        me = (await client.get("/api/v1/auth/me")).json()
        assert me["can"]["manage_settings"] is False
    # The college admin may still manage people in their college
    await sign_in(client, await person(db_session, the_org, "cadm2", access.ADMINISTRATOR, (ScopeType.college, college.id)))
    assert (await client.get("/api/v1/auth/me")).json()["can"]["manage_people"] is True


async def test_organization_settings(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "frame_ancestors", "https://default-lms.example")
    monkeypatch.setattr(settings, "metadata_contact_email", "ops@stacks.example")
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["can"] == {"manage_settings": True, "manage_people": True, "manage_courses": True, "view_reports": True}

    body = (await client.get("/api/v1/admin/organization")).json()
    assert (body["lms_origins"], body["default_lms_origins"]) == (None, ["https://default-lms.example"])
    assert (body["contact_email"], body["default_contact_email"]) == (None, "ops@stacks.example")
    assert body["can_manage_domains"] is False

    resp = await client.patch("/api/v1/admin/organization", json={
        "name": "University of Somewhere", "lms_origins": ["https://uni.brightspace.com", " "],
        "contact_email": "library@uni.edu"})
    body = resp.json()
    assert (body["name"], body["lms_origins"], body["contact_email"]) == (
        "University of Somewhere", ["https://uni.brightspace.com"], "library@uni.edu")
    # The frame policy follows at once
    policy = (await client.get("/api/v1/tenant/frame-policy", headers={"Host": "unknown.example"}))
    assert policy.status_code == 204

    # null goes back to the installation default; [] means no LMS at all
    assert (await client.patch("/api/v1/admin/organization", json={"lms_origins": None})).json()["lms_origins"] is None
    assert (await client.patch("/api/v1/admin/organization", json={"lms_origins": []})).json()["lms_origins"] == []
    bad = await client.patch("/api/v1/admin/organization", json={"lms_origins": ["lms.example.edu"]})
    assert bad.status_code == 422 and "origins" in bad.json()["detail"]
    assert (await client.patch("/api/v1/admin/organization", json={"contact_email": "nope"})).status_code == 422


async def test_domains_are_for_system_admins(client, db_session, org, admin):
    the_org, _ = org
    assert (await client.post("/api/v1/admin/organization/domains", json={"hostname": "stacks.uni.edu"})).status_code == 403
    await sign_in(client, await person(db_session, the_org, "root", system=True))

    body = (await client.post("/api/v1/admin/organization/domains", json={"hostname": "Stacks.Uni.EDU"})).json()
    assert [(d["hostname"], d["is_primary"]) for d in body["domains"]] == [("stacks.uni.edu", True)]
    assert body["address"] == "https://stacks.uni.edu"
    body = (await client.post("/api/v1/admin/organization/domains", json={"hostname": "lists.uni.edu"})).json()
    second = next(d for d in body["domains"] if d["hostname"] == "lists.uni.edu")
    assert second["is_primary"] is False
    assert (await client.post("/api/v1/admin/organization/domains", json={"hostname": "lists.uni.edu"})).status_code == 409
    assert (await client.post("/api/v1/admin/organization/domains", json={"hostname": "not a host"})).status_code == 422

    body = (await client.post(f"/api/v1/admin/organization/domains/{second['id']}/primary")).json()
    assert body["address"] == "https://lists.uni.edu"
    body = (await client.delete(f"/api/v1/admin/organization/domains/{second['id']}")).json()
    assert [d["hostname"] for d in body["domains"]] == ["stacks.uni.edu"]


async def test_library_connections(client, db_session, admin):
    listed = (await client.get("/api/v1/admin/sources")).json()
    assert [(s["kind"], s["configured"]) for s in listed] == [("alma", False), ("primo", False), ("libkey", False)]

    assert (await client.put("/api/v1/admin/sources/alma", json={"config": {"region": "na"}})).status_code == 422
    assert (await client.put("/api/v1/admin/sources/alma", json={"config": {"region": "mars"}, "api_key": "k"})).status_code == 422
    saved = (await client.put("/api/v1/admin/sources/alma", json={"config": {"region": "na"}, "api_key": "secret-1"})).json()
    assert (saved["configured"], saved["key_set"], saved["is_active"]) == (True, True, True)
    assert "secret-1" not in str(saved)

    # Changing settings without a key keeps the stored key
    await client.put("/api/v1/admin/sources/alma", json={"config": {"region": "eu"}, "is_active": False})
    row = await db_session.scalar(select(LibrarySource).execution_options(populate_existing=True))
    assert (row.config["region"], row.is_active, credentials.decrypt(row.api_key_encrypted)) == ("eu", False, "secret-1")

    assert (await client.delete("/api/v1/admin/sources/alma")).status_code == 204
    assert (await client.delete("/api/v1/admin/sources/alma")).status_code == 404


async def test_test_connection_uses_form_values_or_the_stored_key(client, admin):
    fake = FakeSources()
    fake.routes[("api-na.hosted.exlibrisgroup.com", "/almaws/v1/bibs/test")] = (200, "x")

    async def fake_client():
        async with fake.client() as http:
            yield http

    app.dependency_overrides[get_http_client] = fake_client
    assert (await client.post("/api/v1/admin/sources/alma/test", json={"config": {"region": "na"}})).status_code == 422

    ok = (await client.post("/api/v1/admin/sources/alma/test", json={"config": {"region": "na"}, "api_key": "typed"})).json()
    assert ok["ok"] is True
    assert fake.requests[-1].headers["Authorization"] == "apikey typed"

    await client.put("/api/v1/admin/sources/alma", json={"config": {"region": "na"}, "api_key": "stored"})
    await client.post("/api/v1/admin/sources/alma/test", json={})
    assert fake.requests[-1].headers["Authorization"] == "apikey stored"

    fake.routes[("api-na.hosted.exlibrisgroup.com", "/almaws/v1/bibs/test")] = (400, "bad")
    refused = (await client.post("/api/v1/admin/sources/alma/test", json={})).json()
    assert refused["ok"] is False and "refused" in refused["message"]


async def test_link_resolution_settings_and_try(client, admin):
    body = (await client.get("/api/v1/admin/link-resolution")).json()
    assert body["stack"] == ["libkey", "alma", "open_access"]
    assert body["available"] == {"libkey": False, "alma": False, "open_access": True}

    dup = await client.put("/api/v1/admin/link-resolution", json={"stack": ["alma", "alma"]})
    assert dup.status_code == 422
    saved = (await client.put("/api/v1/admin/link-resolution",
                              json={"stack": [], "cache_ttl_seconds": 3600, "step_timeout_seconds": 1.5})).json()
    assert (saved["stack"], saved["cache_ttl_seconds"], saved["step_timeout_seconds"]) == ([], 3600, 1.5)
    assert (await client.put("/api/v1/admin/link-resolution", json={"step_timeout_seconds": 60})).status_code == 422

    tried = (await client.post("/api/v1/admin/link-resolution/try", json={"query": "https://doi.org/10.1000/xyz"})).json()
    assert (tried["resolved_by"], tried["url"]) == ("fallback", "https://doi.org/10.1000/xyz")
    assert (await client.post("/api/v1/admin/link-resolution/try", json={"query": "nothing here"})).status_code == 422
