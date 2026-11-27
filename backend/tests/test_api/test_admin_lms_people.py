"""Administration: LMS registrations, and people and roles."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    College,
    CourseTemplate,
    Department,
    LtiDeployment,
    LtiPlatform,
    Organization,
    OrganizationDomain,
    ScopeType,
)
from app.services import access, lti_service
from tests.test_api.test_admin import person, sign_in

BRIGHTSPACE = {
    "issuer": "https://uni.brightspace.com",
    "client_id": "abc-123",
    "auth_login_url": "https://uni.brightspace.com/d2l/lti/authenticate",
    "auth_token_url": "https://auth.brightspace.com/core/connect/token",
    "jwks_url": "https://uni.brightspace.com/d2l/.well-known/jwks",
    "deployment_ids": ["dep-1", "dep-1", " "],
}


@pytest.fixture
async def uni(db_session: AsyncSession):
    org = Organization(name="Uni", slug="uni")
    arts = College(organization=org, name="Arts", code="ARTS")
    science = College(organization=org, name="Science", code="SCI")
    history = Department(college=arts, name="History", code="HIST")
    biology = Department(college=science, name="Biology", code="BIO")
    hist101 = CourseTemplate(department=history, code="HIST101", name="Methods")
    db_session.add_all([org, arts, science, history, biology, hist101])
    await db_session.flush()
    other = Organization(name="Elsewhere", slug="elsewhere")
    db_session.add(other)
    await db_session.flush()
    db_session.add(OrganizationDomain(organization_id=org.id, hostname="stacks.uni.edu", is_primary=True))
    await db_session.commit()
    return {"org": org, "arts": arts, "science": science, "history": history, "biology": biology,
            "hist101": hist101, "other": other}


async def org_admin(client, db, uni):
    user = await person(db, uni["org"], "admin", access.ADMINISTRATOR, (ScopeType.organization, uni["org"].id))
    await sign_in(client, user)
    return user


# ── LMS ──────────────────────────────────────────────────────────────────────


async def test_register_and_manage_an_lms(client, db_session, uni):
    await org_admin(client, db_session, uni)
    body = (await client.get("/api/v1/admin/lms")).json()
    assert body["tool"] == {
        "login_url": "https://stacks.uni.edu/lti/login",
        "redirect_url": "https://stacks.uni.edu/lti/launch",
        "target_link_uri": "https://stacks.uni.edu/lti/launch",
        "jwks_url": "https://stacks.uni.edu/lti/jwks",
    }
    assert body["platforms"] == []

    resp = await client.post("/api/v1/admin/lms", json=BRIGHTSPACE)
    assert resp.status_code == 201
    [platform] = resp.json()["platforms"]
    assert [d["deployment_id"] for d in platform["deployments"]] == ["dep-1"]  # de-duplicated, blanks dropped
    assert "tool_private_key" not in str(resp.json())
    stored = await db_session.scalar(select(LtiPlatform))
    # Encrypted at rest, and still readable for signing
    assert "PRIVATE KEY" not in stored.tool_private_key_encrypted
    assert lti_service.tool_private_key(stored).startswith("-----BEGIN PRIVATE KEY-----")
    # The new key is published for the LMS
    jwks = (await client.get("/lti/jwks")).json()
    assert stored.tool_key_id in [k["kid"] for k in jwks["keys"]]

    assert (await client.post("/api/v1/admin/lms", json=BRIGHTSPACE)).status_code == 409
    bad = await client.post("/api/v1/admin/lms", json={**BRIGHTSPACE, "client_id": "x", "jwks_url": "http://insecure"})
    assert bad.status_code == 422

    pid = platform["id"]
    resp = await client.post(f"/api/v1/admin/lms/{pid}/deployments", json={"deployment_id": "dep-2", "label": "Sandbox"})
    assert [d["deployment_id"] for d in resp.json()["platforms"][0]["deployments"]] == ["dep-1", "dep-2"]
    assert (await client.post(f"/api/v1/admin/lms/{pid}/deployments", json={"deployment_id": "dep-2"})).status_code == 409

    dep1 = next(d for d in resp.json()["platforms"][0]["deployments"] if d["deployment_id"] == "dep-1")
    resp = await client.delete(f"/api/v1/admin/lms/{pid}/deployments/{dep1['id']}")
    assert next(d for d in resp.json()["platforms"][0]["deployments"] if d["id"] == dep1["id"])["is_active"] is False
    # Adding it again turns it back on
    resp = await client.post(f"/api/v1/admin/lms/{pid}/deployments", json={"deployment_id": "dep-1"})
    assert all(d["is_active"] for d in resp.json()["platforms"][0]["deployments"])
    assert await db_session.scalar(select(LtiDeployment.organization_id).limit(1)) == uni["org"].id

    resp = await client.patch(f"/api/v1/admin/lms/{pid}", json={"is_active": False, "jwks_url": "https://uni.brightspace.com/new-jwks"})
    p = resp.json()["platforms"][0]
    assert (p["is_active"], p["jwks_url"]) == (False, "https://uni.brightspace.com/new-jwks")
    assert (await client.patch(f"/api/v1/admin/lms/{pid}", json={"issuer": "https://x"})).status_code == 422


async def test_lms_is_organization_scoped_and_admin_only(client, db_session, uni):
    other_platform = LtiPlatform(organization_id=uni["other"].id, issuer="https://other.edu", client_id="o",
                                 auth_login_url="https://other.edu/a", auth_token_url="https://other.edu/t",
                                 jwks_url="https://other.edu/j", tool_private_key_encrypted="x", tool_public_key="x", tool_key_id="k")
    db_session.add(other_platform)
    await db_session.commit()
    await org_admin(client, db_session, uni)
    assert (await client.get("/api/v1/admin/lms")).json()["platforms"] == []
    assert (await client.patch(f"/api/v1/admin/lms/{other_platform.id}", json={"is_active": False})).status_code == 404

    await sign_in(client, await person(db_session, uni["org"], "cadm", access.ADMINISTRATOR, (ScopeType.college, uni["arts"].id)))
    assert (await client.get("/api/v1/admin/lms")).status_code == 403


# ── People ───────────────────────────────────────────────────────────────────


async def test_org_admin_sees_everyone_and_gives_roles_anywhere(client, db_session, uni):
    me = await org_admin(client, db_session, uni)
    ada = await person(db_session, uni["org"], "ada")
    await person(db_session, uni["other"], "stranger")

    page = (await client.get("/api/v1/admin/people")).json()
    assert {p["display_name"] for p in page["people"]} == {"admin", "ada"}  # not other organizations
    assert page["roles"] == ["Administrator", "Librarian", "Instructor", "Viewer"]
    assert page["can_change_accounts"] is True
    assert (await client.get("/api/v1/admin/people", params={"q": "ADA"})).json()["total"] == 1

    scopes = (await client.get("/api/v1/admin/scopes")).json()
    assert [s["label"] for s in scopes] == ["All of Uni", "Arts", "Science", "Arts › History", "Science › Biology", "HIST101 Methods"]

    resp = await client.post(f"/api/v1/admin/people/{ada.id}/roles",
                             json={"role": "Librarian", "scope_type": "department", "scope_id": str(uni["history"].id)})
    assert resp.status_code == 201
    assert (resp.json()["role"], resp.json()["scope"]["label"]) == ("Librarian", "Arts › History")
    ada_row = next(p for p in (await client.get("/api/v1/admin/people")).json()["people"] if p["id"] == str(ada.id))
    assert [(r["role"], r["scope"]["label"], r["can_remove"]) for r in ada_row["roles"]] == [("Librarian", "Arts › History", True)]

    assert (await client.post(f"/api/v1/admin/people/{ada.id}/roles",
                              json={"role": "Wizard", "scope_type": "organization", "scope_id": str(uni["org"].id)})).status_code == 422
    # Can't give roles in another organization
    assert (await client.post(f"/api/v1/admin/people/{ada.id}/roles",
                              json={"role": "Viewer", "scope_type": "organization", "scope_id": str(uni["other"].id)})).status_code == 403

    assert (await client.delete(f"/api/v1/admin/people/{ada.id}/roles/{resp.json()['id']}")).status_code == 204
    # ...but not lock yourself out
    own = next(p for p in (await client.get("/api/v1/admin/people")).json()["people"] if p["id"] == str(me.id))["roles"][0]
    assert (await client.delete(f"/api/v1/admin/people/{me.id}/roles/{own['id']}")).status_code == 409


async def test_college_admin_works_within_their_college(client, db_session, uni):
    cadm = await person(db_session, uni["org"], "cadm", access.ADMINISTRATOR, (ScopeType.college, uni["arts"].id))
    bob = await person(db_session, uni["org"], "bob", access.VIEWER, (ScopeType.college, uni["science"].id))
    await sign_in(client, cadm)

    scopes = (await client.get("/api/v1/admin/scopes")).json()
    assert [s["label"] for s in scopes] == ["Arts", "Arts › History", "HIST101 Methods"]

    give = lambda scope_type, scope_id: client.post(  # noqa: E731
        f"/api/v1/admin/people/{bob.id}/roles", json={"role": "Librarian", "scope_type": scope_type, "scope_id": str(scope_id)})
    assert (await give("department", uni["history"].id)).status_code == 201
    assert (await give("course_template", uni["hist101"].id)).status_code == 201
    assert (await give("department", uni["biology"].id)).status_code == 403
    assert (await give("organization", uni["org"].id)).status_code == 403

    page = (await client.get("/api/v1/admin/people")).json()
    assert page["can_change_accounts"] is False
    bob_roles = {r["scope"]["label"]: r for r in next(p for p in page["people"] if p["id"] == str(bob.id))["roles"]}
    assert bob_roles["Science"]["can_remove"] is False  # outside their college
    assert (await client.delete(f"/api/v1/admin/people/{bob.id}/roles/{bob_roles['Science']['id']}")).status_code == 403
    assert (await client.patch(f"/api/v1/admin/people/{bob.id}", json={"is_active": False})).status_code == 403


async def test_accounts_on_and_off(client, db_session, uni):
    me = await org_admin(client, db_session, uni)
    ada = await person(db_session, uni["org"], "ada")
    root = await person(db_session, uni["org"], "root", system=True)
    resp = await client.patch(f"/api/v1/admin/people/{ada.id}", json={"is_active": False})
    assert resp.json()["is_active"] is False
    # A turned-off account can't sign in
    client.headers.pop("Authorization")
    signin = await client.post("/api/v1/auth/local/login", json={"email": "ada@uni.edu", "password": "long-enough-pw"})
    assert signin.status_code in (401, 403)
    await sign_in(client, me)
    assert (await client.patch(f"/api/v1/admin/people/{me.id}", json={"is_active": False})).status_code == 409
    assert (await client.patch(f"/api/v1/admin/people/{root.id}", json={"is_active": False})).status_code == 403


async def test_people_screens_need_people_manage(client, db_session, uni):
    await sign_in(client, await person(db_session, uni["org"], "lib", access.LIBRARIAN, (ScopeType.organization, uni["org"].id)))
    assert (await client.get("/api/v1/admin/people")).status_code == 403
    assert (await client.get("/api/v1/admin/scopes")).status_code == 403
