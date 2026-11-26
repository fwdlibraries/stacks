"""Single sign-on (OpenID Connect) against a fake identity provider."""
import base64
import hashlib
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.models import (
    Organization,
    OrganizationDomain,
    Role,
    ScopeType,
    SsoConfig,
    User,
    UserIdentity,
    UserRoleAssignment,
)
from app.routers.ingest import get_http_client
from app.services import access, credentials, sso
from app.services.auth_service import AuthService

TID = "11111111-2222-3333-4444-555555555555"
ENTRA = f"https://login.microsoftonline.com/{TID}/v2.0"
HOST = {"Host": "stacks.uni.edu"}


class FakeIdP:
    """Discovery, keys and a token endpoint that checks PKCE, like a real provider."""

    def __init__(self, issuer: str = ENTRA, client_id: str = "stacks-client", secret: str = "s3cret"):
        self.issuer, self.client_id, self.secret = issuer, client_id, secret
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes: dict[str, dict] = {}
        self.token_overrides: dict = {}

    def jwks(self) -> dict:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}

    def authorize(self, location: str, **claims) -> str:
        """What the provider does at its login page: remember the request, return a code."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        code = uuid.uuid4().hex
        self.codes[code] = {"q": q, "claims": claims}
        return code

    def id_token(self, request_q: dict, claims: dict) -> str:
        now = int(time.time())
        body = {"iss": self.issuer, "aud": self.client_id, "sub": "pairwise-sub", "iat": now, "exp": now + 300,
                "nonce": request_q["nonce"], **claims, **self.token_overrides}
        return jwt.encode(body, self.key, algorithm="RS256", headers={"kid": "k1"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == f"{self.issuer}/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": self.issuer, "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token", "jwks_uri": f"{self.issuer}/keys"})
        if url == f"{self.issuer}/keys":
            return httpx.Response(200, json=self.jwks())
        if url == f"{self.issuer}/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            grant = self.codes.pop(form.get("code", ""), None)
            if grant is None or form.get("client_secret") != self.secret or form.get("client_id") != self.client_id:
                return httpx.Response(400, json={"error": "invalid_grant"})
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
            if challenge != grant["q"]["code_challenge"] or form["redirect_uri"] != grant["q"]["redirect_uri"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token(grant["q"], grant["claims"]), "token_type": "Bearer"})
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def fresh_caches():
    sso._discovery_cache.clear()
    sso._jwks_cache.clear()


@pytest.fixture
async def env(db_session: AsyncSession):
    org = Organization(name="Uni", slug="uni")
    db_session.add(org)
    await db_session.flush()
    db_session.add(OrganizationDomain(organization_id=org.id, hostname="stacks.uni.edu", is_primary=True))
    config = SsoConfig(organization_id=org.id, issuer=ENTRA, client_id="stacks-client",
                       client_secret_encrypted=credentials.encrypt("s3cret"), button_label="Sign in with Uni",
                       allowed_domains=["uni.edu"])
    db_session.add(config)
    await db_session.commit()
    idp = FakeIdP()

    async def fake_client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(idp.handler)) as http:
            yield http

    app.dependency_overrides[get_http_client] = fake_client
    return org, config, idp


ADA = {"tid": TID, "oid": "oid-ada", "preferred_username": "ada@uni.edu", "name": "Ada Lovelace"}


async def sign_in(client: AsyncClient, idp: FakeIdP, *, host=HOST, next_path="/lists/x", **claims) -> httpx.Response:
    start = await client.get("/api/v1/auth/oidc/start", params={"next": next_path}, headers=host)
    assert start.status_code == 303, start.text
    if "/login?" in start.headers["location"]:
        return start
    code = idp.authorize(start.headers["location"], **claims)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    return await client.get("/api/v1/auth/oidc/callback", params={"code": code, "state": state}, headers=host)


def error_of(resp: httpx.Response) -> str | None:
    loc = resp.headers["location"]
    return parse_qs(urlsplit(loc).query)["sso_error"][0] if loc.startswith("/login?") else None


async def tokens(client: AsyncClient, resp: httpx.Response) -> dict:
    code = parse_qs(urlsplit(resp.headers["location"]).query)["code"][0]
    return (await client.post("/api/v1/auth/lti/exchange", json={"code": code})).json()


async def invite(db: AsyncSession, org, email="ada@uni.edu", role=access.LIBRARIAN) -> User:
    from datetime import UTC, datetime
    user = User(organization_id=org.id, email=email, display_name="Ada (invited)", invited_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    await access.grant(db, user, role, ScopeType.organization, org.id)
    await db.commit()
    return user


async def test_sign_in_page_info(client, env):
    assert (await client.get("/api/v1/auth/oidc", headers=HOST)).json() == {
        "enabled": True, "label": "Sign in with Uni", "passwords_allowed": True}
    assert (await client.get("/api/v1/auth/oidc", headers={"Host": "elsewhere.edu"})).json()["enabled"] is False


async def test_the_request_uses_pkce_state_and_nonce(client, env):
    start = await client.get("/api/v1/auth/oidc/start", headers=HOST)
    q = {k: v[0] for k, v in parse_qs(urlsplit(start.headers["location"]).query).items()}
    assert start.headers["location"].startswith(f"{ENTRA}/authorize?")
    assert (q["response_type"], q["code_challenge_method"], q["scope"]) == ("code", "S256", "openid email profile")
    assert q["redirect_uri"] == "https://stacks.uni.edu/api/v1/auth/oidc/callback"
    assert len(q["state"]) > 30 and len(q["nonce"]) > 30 and len(q["code_challenge"]) == 43


async def test_invited_person_signs_in_and_is_linked_by_their_entra_id(client, db_session, env):
    org, _, idp = env
    invited = await invite(db_session, org)
    resp = await sign_in(client, idp, **ADA)
    assert resp.headers["location"].startswith("/launch?code=")
    session = await tokens(client, resp)
    assert session["next"] == "/lists/x"
    me = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session['access_token']}"})).json()
    assert (me["id"], me["can"]["view_reports"]) == (str(invited.id), True)  # the invitation's role
    identity = await db_session.scalar(select(UserIdentity))
    assert identity.provider_user_id == f"entra:{TID}:oid-ada"

    # Later sign-ins go by the Entra ID, whatever the email says now
    resp = await sign_in(client, idp, **{**ADA, "preferred_username": "a.lovelace@uni.edu"})
    assert (await tokens(client, resp))["access_token"]
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_nobody_is_let_in_without_an_invitation_by_default(client, db_session, env):
    _, _, idp = env
    assert "Ask your library to invite you" in error_of(await sign_in(client, idp, **ADA))
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_signup_creates_an_account_with_no_roles_in_allowed_domains_only(client, db_session, env):
    _, config, idp = env
    config.allow_signup = True
    await db_session.commit()
    session = await tokens(client, await sign_in(client, idp, **ADA))
    me = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session['access_token']}"})).json()
    assert (me["email"], me["display_name"], any(me["can"].values())) == ("ada@uni.edu", "Ada Lovelace", False)
    err = error_of(await sign_in(client, idp, **{**ADA, "oid": "oid-eve", "preferred_username": "eve@evil.com"}))
    assert "domain isn't allowed" in err


async def test_email_links_an_invitation_only_when_the_provider_vouches_for_it(client, db_session, env):
    org, config, idp = env
    config.issuer = idp.issuer = "https://idp.uni.edu"  # a non-Entra provider
    await db_session.commit()
    await invite(db_session, org)
    unverified = {"sub": "s-1", "email": "ada@uni.edu", "email_verified": False}
    assert "invite you" in error_of(await sign_in(client, idp, **unverified))
    verified = {"sub": "s-1", "email": "ada@uni.edu", "email_verified": True}
    assert (await sign_in(client, idp, **verified)).headers["location"].startswith("/launch?code=")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"tid": "99999999-9999-9999-9999-999999999999"}, "different organization"),  # another Entra tenant
        ({"aud": "someone-else"}, "couldn't be verified"),
        ({"iss": "https://login.microsoftonline.com/other/v2.0"}, "couldn't be verified"),
        ({"exp": int(time.time()) - 3600}, "couldn't be verified"),
        ({"nonce": "replayed"}, "doesn't belong to this sign-in"),
    ],
)
async def test_tokens_that_are_not_for_us_are_refused(client, db_session, env, override, message):
    org, _, idp = env
    await invite(db_session, org)
    idp.token_overrides = override
    assert message in error_of(await sign_in(client, idp, **ADA))


@pytest.mark.filterwarnings("ignore:The HMAC key")  # the weak key is the point
async def test_a_token_signed_some_other_way_is_refused(client, db_session, env, monkeypatch):
    org, _, idp = env
    await invite(db_session, org)
    # e.g. HS256 with the client secret, or "none": only asymmetric algorithms are accepted
    monkeypatch.setattr(idp, "id_token", lambda q, claims: jwt.encode(
        {"iss": ENTRA, "aud": "stacks-client", "sub": "x", "iat": int(time.time()), "exp": int(time.time()) + 300,
         "nonce": q["nonce"], **claims}, "s3cret", algorithm="HS256"))
    assert "algorithm" in error_of(await sign_in(client, idp, **ADA))


async def test_state_is_single_use_and_bound_to_the_site(client, db_session, env):
    org, _, idp = env
    await invite(db_session, org)
    start = await client.get("/api/v1/auth/oidc/start", headers=HOST)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    code = idp.authorize(start.headers["location"], **ADA)
    ok = await client.get("/api/v1/auth/oidc/callback", params={"code": code, "state": state}, headers=HOST)
    assert ok.headers["location"].startswith("/launch")
    again = await client.get("/api/v1/auth/oidc/callback", params={"code": code, "state": state}, headers=HOST)
    assert "expired" in error_of(again)
    # A state begun on one organization's site can't finish on another's
    other = Organization(name="Other", slug="other")
    db_session.add(other)
    await db_session.flush()
    db_session.add(OrganizationDomain(organization_id=other.id, hostname="stacks.other.edu", is_primary=True))
    db_session.add(SsoConfig(organization_id=other.id, issuer=ENTRA, client_id="c", client_secret_encrypted=credentials.encrypt("x")))
    await db_session.commit()
    start = await client.get("/api/v1/auth/oidc/start", headers=HOST)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    moved = await client.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state}, headers={"Host": "stacks.other.edu"})
    assert "doesn't belong to this site" in error_of(moved)


async def test_pkce_is_enforced(client, db_session, env):
    org, _, idp = env
    await invite(db_session, org)
    start = await client.get("/api/v1/auth/oidc/start", headers=HOST)
    q = parse_qs(urlsplit(start.headers["location"]).query)
    # A code issued for someone else's request (different challenge) won't redeem
    stolen = idp.authorize(start.headers["location"].replace(q["code_challenge"][0], "x" * 43), **ADA)
    resp = await client.get("/api/v1/auth/oidc/callback", params={"code": stolen, "state": q["state"][0]}, headers=HOST)
    assert "didn't accept" in error_of(resp)


async def test_mfa_can_be_required(client, db_session, env):
    org, config, idp = env
    config.require_mfa = True
    await db_session.commit()
    await invite(db_session, org)
    assert "multi-factor" in error_of(await sign_in(client, idp, **{**ADA, "amr": ["pwd"]}))
    assert (await sign_in(client, idp, **{**ADA, "amr": ["pwd", "mfa"]})).headers["location"].startswith("/launch")


async def test_roles_follow_the_providers_role_claims(client, db_session, env):
    org, config, idp = env
    config.role_mapping = {"Stacks.Librarian": "Librarian", "Stacks.Admin": "Administrator"}
    await db_session.commit()
    user = await invite(db_session, org, role=access.VIEWER)  # granted in Stacks: never touched by sync

    async def roles():
        rows = await db_session.execute(
            select(Role.name, UserRoleAssignment.source).join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id == user.id).execution_options(populate_existing=True))
        return sorted((n, s) for n, s in rows)

    await sign_in(client, idp, **{**ADA, "roles": ["Stacks.Librarian", "Unmapped.Thing"]})
    assert await roles() == [("Librarian", "sso"), ("Viewer", None)]
    await sign_in(client, idp, **{**ADA, "roles": ["Stacks.Admin"]})
    assert await roles() == [("Administrator", "sso"), ("Viewer", None)]
    await sign_in(client, idp, **ADA)  # no roles claimed
    assert await roles() == [("Viewer", None)]


async def test_turned_off_accounts_cant_sign_in(client, db_session, env):
    org, _, idp = env
    user = await invite(db_session, org)
    user.is_active = False
    await db_session.commit()
    assert "turned off" in error_of(await sign_in(client, idp, **ADA))


async def test_passwords_can_be_turned_off_except_for_system_admins(client, db_session, env):
    org, config, _ = env
    config.disable_passwords = True
    for name, system in (("staff", False), ("root", True)):
        db_session.add(User(organization_id=org.id, email=f"{name}@uni.edu", display_name=name, is_system_admin=system,
                            password_hash=AuthService.hash_password("long-enough-pw")))
    await db_session.commit()
    login = lambda email: client.post("/api/v1/auth/local/login", json={"email": email, "password": "long-enough-pw"})  # noqa: E731
    assert (await login("staff@uni.edu")).status_code == 403
    assert (await login("root@uni.edu")).status_code == 200
    assert (await client.get("/api/v1/auth/oidc", headers=HOST)).json()["passwords_allowed"] is False


async def test_provider_errors_and_cancel(client, env):
    resp = await client.get("/api/v1/auth/oidc/callback", params={"error": "access_denied", "state": "x"}, headers=HOST)
    assert "cancelled" in error_of(resp)


# ── Administration ───────────────────────────────────────────────────────────


@pytest.fixture
async def admin_client(client, db_session):
    from tests.test_api.test_admin import person
    from tests.test_api.test_admin import sign_in as admin_sign_in

    org = Organization(name="Org", slug="org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(OrganizationDomain(organization_id=org.id, hostname="stacks.org.edu", is_primary=True))
    await db_session.commit()
    await admin_sign_in(client, await person(db_session, org, "admin", access.ADMINISTRATOR, (ScopeType.organization, org.id)))
    return org


GOOD = {"issuer": ENTRA, "client_id": "abc", "client_secret": "top-secret", "allowed_domains": ["Org.EDU", " "],
        "button_label": "Sign in with Org", "role_mapping": {"Stacks.Librarian": "Librarian"}}


async def test_sso_settings(client, admin_client):
    blank = (await client.get("/api/v1/admin/sso")).json()
    assert (blank["configured"], blank["redirect_uri"]) == (False, "https://stacks.org.edu/api/v1/auth/oidc/callback")

    saved = (await client.put("/api/v1/admin/sso", json=GOOD)).json()
    assert (saved["configured"], saved["secret_set"], saved["allowed_domains"]) == (True, True, ["org.edu"])
    assert "top-secret" not in str(saved)
    # Keep the secret when it's left out
    assert (await client.put("/api/v1/admin/sso", json={**GOOD, "client_secret": None, "require_mfa": True})).json()["require_mfa"]

    for bad, why in (
        ({"issuer": "https://login.microsoftonline.com/common/v2.0"}, "any Microsoft customer"),
        ({"issuer": "http://idp.org.edu"}, "https://"),
        ({"allowed_domains": [], "allow_signup": True, "role_mapping": {}}, "email domains"),
        ({"role_mapping": {"X": "Wizard"}}, "Unknown Stacks roles"),
    ):
        resp = await client.put("/api/v1/admin/sso", json={**GOOD, **bad})
        assert resp.status_code == 422 and why in resp.json()["detail"], bad
    assert (await client.delete("/api/v1/admin/sso")).status_code == 204


async def test_first_setup_needs_the_secret(client, admin_client):
    assert (await client.put("/api/v1/admin/sso", json={**GOOD, "client_secret": None})).status_code == 422


async def test_invitations(client, db_session, admin_client):
    org = admin_client
    resp = await client.post("/api/v1/admin/people/invite", json={
        "email": "New.Person@org.edu", "display_name": "New Person", "role": "Librarian",
        "scope_type": "organization", "scope_id": str(org.id)})
    assert resp.status_code == 201
    body = resp.json()
    assert (body["email"], body["invited"], body["has_password"], [r["role"] for r in body["roles"]]) == (
        "new.person@org.edu", True, False, ["Librarian"])
    dup = await client.post("/api/v1/admin/people/invite", json={
        "email": "new.person@org.edu", "display_name": "x", "role": "Viewer", "scope_type": "organization", "scope_id": str(org.id)})
    assert dup.status_code == 409
    elsewhere = await client.post("/api/v1/admin/people/invite", json={
        "email": "x@org.edu", "display_name": "x", "role": "Viewer", "scope_type": "organization", "scope_id": str(uuid.uuid4())})
    assert elsewhere.status_code == 403
