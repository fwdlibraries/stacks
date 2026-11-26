"""Organizations by hostname, and per-organization settings with .env fallbacks."""
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingest.resolvers import ResolveContext
from app.ingest.resolvers.crossref import user_agent
from app.models.models import Organization, OrganizationDomain, User
from app.services.auth_service import AuthService
from app.services.tenancy import OrgSettings, normalize_host, tenant_for_host
from tests.test_api.test_lti import CLIENT_ID, ISSUER, launch, platform, store  # noqa: F401  (fixtures)


async def add_domain(db: AsyncSession, org: Organization, host: str, primary: bool = True) -> None:
    db.add(OrganizationDomain(organization_id=org.id, hostname=host, is_primary=primary))
    await db.commit()


@pytest.fixture
async def two_schools(db_session: AsyncSession):
    alpha = Organization(name="Alpha College", slug="alpha", settings={"frame_ancestors": ["https://alpha.brightspace.com"]})
    beta = Organization(name="Beta University", slug="beta")
    db_session.add_all([alpha, beta])
    await db_session.flush()
    await add_domain(db_session, alpha, "stacks.alpha.edu")
    await add_domain(db_session, beta, "lists.beta.edu")
    return alpha, beta


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Stacks.Alpha.EDU", "stacks.alpha.edu"), ("stacks.alpha.edu:443", "stacks.alpha.edu"),
     ("stacks.alpha.edu.", "stacks.alpha.edu"), ("localhost:5173", "localhost"), ("[::1]:8000", None),
     ("evil.com/x", None), ("", None)],
)
def test_normalize_host(raw, expected):
    assert normalize_host(raw) == expected


async def test_host_picks_the_organization(client, db_session, two_schools, monkeypatch):
    monkeypatch.setattr(settings, "default_organization", "")
    alpha = (await client.get("/api/v1/tenant", headers={"Host": "stacks.alpha.edu"})).json()
    assert (alpha["name"], alpha["slug"], alpha["theme"]["mode"]) == ("Alpha College", "alpha", "stacks")
    assert (await client.get("/api/v1/tenant", headers={"Host": "LISTS.beta.edu:443"})).json()["slug"] == "beta"
    unknown = (await client.get("/api/v1/tenant", headers={"Host": "unknown.example"})).json()
    assert (unknown["name"], unknown["slug"]) == (None, None)


async def test_default_organization_and_strict_mode(client, db_session, two_schools, monkeypatch):
    monkeypatch.setattr(settings, "default_organization", "beta")
    assert (await client.get("/api/v1/tenant", headers={"Host": "localhost:5173"})).json()["slug"] == "beta"
    tenant = await tenant_for_host(db_session, "localhost")
    assert tenant.by_domain is False  # a fallback, not the school's own hostname

    monkeypatch.setattr(settings, "default_organization", "")
    monkeypatch.setattr(settings, "require_known_host", True)
    assert (await client.get("/api/v1/tenant", headers={"Host": "unknown.example"})).status_code == 404
    assert (await client.get("/api/v1/tenant", headers={"Host": "stacks.alpha.edu"})).status_code == 200


async def test_frame_policy_per_organization(client, db_session, two_schools, monkeypatch):
    monkeypatch.setattr(settings, "frame_ancestors", "https://default-lms.example")

    async def policy(host):
        resp = await client.get("/api/v1/tenant/frame-policy", headers={"Host": host})
        assert resp.status_code == 204
        # The page policy: everything from Stacks itself, framed by the organization's LMS
        policy = resp.headers["content-security-policy"]
        assert "default-src 'self'" in policy and "img-src 'self' data:" in policy
        return next(part for part in policy.split("; ") if part.startswith("frame-ancestors"))

    assert await policy("stacks.alpha.edu") == "frame-ancestors 'self' https://alpha.brightspace.com"
    # Beta hasn't set its own: the installation default applies
    assert await policy("lists.beta.edu") == "frame-ancestors 'self' https://default-lms.example"


async def test_password_sign_in_is_limited_to_the_hostnames_organization(client, db_session, two_schools):
    alpha, beta = two_schools
    for org in (alpha, beta):  # the same person at two schools
        db_session.add(User(organization=org, email="sam@shared.edu", display_name="Sam",
                            password_hash=AuthService.hash_password(f"{org.slug}-password")))
    await db_session.commit()

    async def login(host, password):
        return await client.post("/api/v1/auth/local/login", headers={"Host": host},
                                 json={"email": "sam@shared.edu", "password": password})

    assert (await login("stacks.alpha.edu", "alpha-password")).status_code == 200
    assert (await login("lists.beta.edu", "beta-password")).status_code == 200
    assert (await login("lists.beta.edu", "alpha-password")).status_code == 401
    # Without a hostname to go by, an email shared across schools is refused (as before)
    assert (await login("unknown.example", "alpha-password")).status_code == 401


async def test_public_lists_only_on_their_organizations_hostname(client, db_session, two_schools):
    resp = await client.get("/api/v1/public/lists/beta/HIST101/fall-2026", headers={"Host": "stacks.alpha.edu"})
    assert resp.status_code == 404
    # On an unclaimed hostname (self-hosted, no domains) any organization's lists are served as before
    resp = await client.get("/api/v1/public/lists/beta/HIST101/fall-2026", headers={"Host": "unknown.example"})
    assert resp.status_code == 404  # beta simply has no such course; the hostname didn't block it


async def test_lti_redirect_uri_uses_the_organizations_address(client, db_session, platform, store, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:5173")
    form = {"iss": ISSUER, "client_id": CLIENT_ID, "login_hint": "u", "target_link_uri": "x"}

    resp = await client.post("/lti/login", data=form)
    assert parse_qs(urlsplit(resp.headers["location"]).query)["redirect_uri"] == ["http://localhost:5173/lti/launch"]

    org = await db_session.get(Organization, platform.organization_id)
    await add_domain(db_session, org, "stacks.test-university.edu")
    resp = await client.post("/lti/login", data=form)
    assert parse_qs(urlsplit(resp.headers["location"]).query)["redirect_uri"] == [
        "https://stacks.test-university.edu/lti/launch"
    ]


async def test_lti_launch_at_another_organizations_hostname_is_refused(client, db_session, platform, store):  # noqa: F811
    other = Organization(name="Other", slug="other")
    db_session.add(other)
    await db_session.flush()
    await add_domain(db_session, other, "stacks.other.edu")
    form = {"iss": ISSUER, "client_id": CLIENT_ID, "login_hint": "u", "target_link_uri": "x"}
    resp = await client.post("/lti/login", data=form, headers={"Host": "stacks.other.edu"})
    assert resp.status_code == 400
    assert "different Stacks site" in resp.text
    assert "frame-ancestors" in resp.headers["content-security-policy"]


async def test_contact_email_per_organization(db_session, two_schools, monkeypatch):
    from app.ingest.sources import context_for

    alpha, beta = two_schools
    monkeypatch.setattr(settings, "metadata_contact_email", "ops@stacks.example")
    alpha.settings = {**alpha.settings, "metadata_contact_email": "library@alpha.edu"}
    await db_session.commit()
    ctx_alpha = await context_for(db_session, alpha.id, http=None)
    ctx_beta = await context_for(db_session, beta.id, http=None)
    assert "mailto:library@alpha.edu" in user_agent(ctx_alpha)
    assert "mailto:ops@stacks.example" in user_agent(ctx_beta)
    assert "mailto:ops@stacks.example" in user_agent(ResolveContext(http=None))


def test_org_settings_validation():
    assert OrgSettings(frame_ancestors=["https://a.edu", "https://a.edu"]).frame_ancestors == ["https://a.edu"]
    for bad in (["lms.example.edu"], ["https://x.edu; script-src *"]):
        with pytest.raises(ValueError):
            OrgSettings(frame_ancestors=bad)
    with pytest.raises(ValueError):
        OrgSettings(metadata_contact_email="not an email")


async def test_hostnames_are_unique(db_session, two_schools):
    from sqlalchemy.exc import IntegrityError

    alpha, beta = two_schools
    alpha_id = alpha.id
    db_session.add(OrganizationDomain(organization_id=beta.id, hostname="stacks.alpha.edu"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    assert (await db_session.scalar(select(OrganizationDomain).where(OrganizationDomain.hostname == "stacks.alpha.edu"))).organization_id == alpha_id
