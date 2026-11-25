"""LTI 1.3 launch tests against a simulated platform (our own RSA key and claims)."""
import html
import time
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import _generate_tool_keys
from app.config import settings
from app.main import app
from app.models.models import (
    CourseOffering,
    CourseTemplate,
    LtiDeployment,
    LtiPlatform,
    LtiUserMapping,
    Organization,
    ReadingList,
    User,
)
from app.services import lti_service
from app.services.ephemeral import MemoryStore, get_ephemeral_store

ISSUER = "https://lms.example.edu"
CLIENT_ID = "stacks-client"
DEPLOYMENT_ID = "dep-1"
LTI = "https://purl.imsglobal.org/spec/lti/claim/"
INSTRUCTOR = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
LEARNER = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"

PLATFORM_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
async def platform(db_session: AsyncSession, monkeypatch):
    org = Organization(name="Test University", slug="test-org")
    private_pem, public_pem = _generate_tool_keys()
    db_session.add(org)
    await db_session.flush()
    platform = LtiPlatform(
        organization_id=org.id,
        issuer=ISSUER,
        client_id=CLIENT_ID,
        auth_login_url="https://lms.example.edu/auth",
        auth_token_url="https://lms.example.edu/token",
        jwks_url="https://lms.example.edu/jwks",
        tool_private_key=private_pem,
        tool_public_key=public_pem,
        tool_key_id="tool-kid",
    )
    db_session.add(platform)
    await db_session.flush()
    db_session.add(LtiDeployment(platform_id=platform.id, deployment_id=DEPLOYMENT_ID, organization_id=org.id))
    await db_session.commit()

    # The platform's JWKS: always its real public key (tokens signed with OTHER_KEY must fail)
    async def fake_signing_key(jwks_url, id_token):
        assert jwks_url == "https://lms.example.edu/jwks"
        return SimpleNamespace(key=PLATFORM_KEY.public_key())

    monkeypatch.setattr(lti_service, "_signing_key", fake_signing_key)
    return platform


@pytest.fixture
def store():
    store = MemoryStore()
    app.dependency_overrides[get_ephemeral_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_ephemeral_store, None)


def claims_for(nonce: str, *, roles=(INSTRUCTOR,), sub="lms-user-1", context=None, custom=None, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": sub,
        "iat": now,
        "exp": now + 300,
        "nonce": nonce,
        "name": "Ada Instructor",
        "email": "ada@example.edu",
        LTI + "version": "1.3.0",
        LTI + "message_type": "LtiResourceLinkRequest",
        LTI + "deployment_id": DEPLOYMENT_ID,
        LTI + "resource_link": {"id": "link-1"},
        LTI + "roles": list(roles),
        LTI + "context": context or {"id": "ctx-1", "label": "HIST101", "title": "Historical Methods"},
        LTI + "custom": custom if custom is not None else {"term": "Fall 2026"},
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


async def start_login(client: AsyncClient) -> tuple[str, str]:
    resp = await client.get(
        "/lti/login", params={"iss": ISSUER, "client_id": CLIENT_ID, "login_hint": "hint-1", "lti_message_hint": "m"}
    )
    assert resp.status_code == 302, resp.text
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    return query["state"][0], query["nonce"][0]


async def launch(client: AsyncClient, *, key=PLATFORM_KEY, claims_fn=None, **claim_kwargs):
    state, nonce = await start_login(client)
    claims = claims_fn(nonce) if claims_fn else claims_for(nonce, **claim_kwargs)
    id_token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "platform-kid"})
    return await client.post("/lti/launch", data={"id_token": id_token, "state": state})


async def exchange(client: AsyncClient, resp) -> dict:
    assert resp.status_code == 303, resp.text
    code = parse_qs(urlsplit(resp.headers["location"]).query)["code"][0]
    out = await client.post("/api/v1/auth/lti/exchange", json={"code": code})
    assert out.status_code == 200, out.text
    return out.json()


# ── Login initiation ─────────────────────────────────────────────────────────

async def test_login_redirects_to_platform_with_oidc_params(client: AsyncClient, platform, store):
    resp = await client.get("/lti/login", params={"iss": ISSUER, "client_id": CLIENT_ID, "login_hint": "u1"})
    assert resp.status_code == 302
    url = urlsplit(resp.headers["location"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://lms.example.edu/auth"
    assert query["response_type"] == "id_token"
    assert query["response_mode"] == "form_post"
    assert query["scope"] == "openid"
    assert query["prompt"] == "none"
    assert query["client_id"] == CLIENT_ID
    # PUBLIC_BASE_URL differs between environments (e.g. a tunnel while testing with a real LMS)
    assert query["redirect_uri"] == f"{settings.public_base_url.rstrip('/')}/lti/launch"
    assert query["login_hint"] == "u1"
    assert query["state"] and query["nonce"] and query["state"] != query["nonce"]


async def test_login_accepts_post(client: AsyncClient, platform, store):
    resp = await client.post("/lti/login", data={"iss": ISSUER, "login_hint": "u1"})
    assert resp.status_code == 302


async def test_unknown_platform_gets_a_readable_error(client: AsyncClient, platform, store):
    resp = await client.get("/lti/login", params={"iss": "https://elsewhere.edu", "login_hint": "u1"})
    assert resp.status_code == 400
    assert "text/html" in resp.headers["content-type"]
    assert "not registered with Stacks" in resp.text


# ── Instructor launches ──────────────────────────────────────────────────────

async def test_first_instructor_launch_provisions_course_and_signs_in(
    client: AsyncClient, db_session: AsyncSession, platform, store
):
    tokens = await exchange(client, await launch(client))

    list_id = tokens["next"].removeprefix("/lists/")
    reading_list = await db_session.get(ReadingList, uuid.UUID(list_id))
    assert reading_list.title == "Historical Methods Reading List"
    assert reading_list.is_published is False
    offering = await db_session.scalar(select(CourseOffering))
    assert offering.term == "fall-2026"
    assert (await db_session.get(CourseTemplate, offering.course_template_id)).code == "HIST101"

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.json()["display_name"] == "Ada Instructor"
    lists = await client.get("/api/v1/lists", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert [item["id"] for item in lists.json()] == [list_id]
    # Teaching the course in the LMS makes them its Instructor in Stacks
    assert (lists.json()[0]["can_edit"], lists.json()[0]["can_publish"]) == (True, True)


async def test_repeat_launches_reuse_course_list_and_user(client: AsyncClient, db_session: AsyncSession, platform, store):
    first = await exchange(client, await launch(client))
    second = await exchange(client, await launch(client))

    assert first["next"] == second["next"]
    assert await db_session.scalar(select(func.count()).select_from(ReadingList)) == 1
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    from app.models.models import UserRoleAssignment
    assert await db_session.scalar(select(func.count()).select_from(UserRoleAssignment)) == 1  # granted once


async def test_next_term_reuses_the_course_list(client: AsyncClient, db_session: AsyncSession, platform, store):
    fall = await exchange(client, await launch(client))
    spring = await exchange(
        client,
        await launch(
            client,
            context={"id": "ctx-2", "label": "HIST101", "title": "Historical Methods"},
            custom={"term": "Spring 2027"},
        ),
    )
    assert fall["next"] == spring["next"]  # same course, same list
    terms = (await db_session.scalars(select(CourseOffering.term).order_by(CourseOffering.term))).all()
    assert terms == ["fall-2026", "spring-2027"]


@pytest.mark.parametrize("custom,expected", [({}, "current"), ({"term": "$Canvas.term.name"}, "current"), ({"term": " 2026/27 Fall! "}, "2026-27-fall")])
async def test_term_from_custom_parameter(client: AsyncClient, db_session: AsyncSession, platform, store, custom, expected):
    await exchange(client, await launch(client, custom=custom))
    assert (await db_session.scalar(select(CourseOffering))).term == expected


async def test_login_code_works_once(client: AsyncClient, platform, store):
    resp = await launch(client)
    code = parse_qs(urlsplit(resp.headers["location"]).query)["code"][0]
    assert (await client.post("/api/v1/auth/lti/exchange", json={"code": code})).status_code == 200
    again = await client.post("/api/v1/auth/lti/exchange", json={"code": code})
    assert again.status_code == 401
    assert "expired" in again.json()["detail"]


async def test_missing_email_gets_placeholder(client: AsyncClient, db_session: AsyncSession, platform, store):
    await exchange(client, await launch(client, email=None))
    user = await db_session.scalar(select(User))
    assert user.email.startswith("lti-") and user.email.endswith("@lms.example.edu.invalid")


# ── Students ─────────────────────────────────────────────────────────────────

async def test_student_before_setup_sees_explanation(client: AsyncClient, db_session: AsyncSession, platform, store):
    resp = await launch(client, roles=(LEARNER,))
    assert resp.status_code == 400
    assert "hasn't been set up yet" in html.unescape(resp.text)
    assert await db_session.scalar(select(func.count()).select_from(CourseOffering)) == 0


async def test_student_goes_to_public_page_without_creating_a_user(
    client: AsyncClient, db_session: AsyncSession, platform, store
):
    await exchange(client, await launch(client))  # instructor sets the course up
    resp = await launch(client, roles=(LEARNER,), sub="student-1")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/public/test-org/HIST101/fall-2026"
    mapped = (await db_session.scalars(select(LtiUserMapping.lti_user_id))).all()
    assert mapped == ["lms-user-1"]


# ── Validation failures ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "case,message",
    [
        ("wrong_key", "could not be verified"),
        ("wrong_nonce", "could not be verified"),
        ("wrong_audience", "could not be verified"),
        ("wrong_issuer", "could not be verified"),
        ("expired", "could not be verified"),
        ("multi_aud_without_azp", "different tool"),
        ("lti_1_1", "LTI 1.3"),
        ("deep_linking", "isn't supported yet"),
        ("unknown_deployment", "deployment is not registered"),
        ("no_context", "inside a course"),
    ],
)
async def test_invalid_launches_are_refused(client: AsyncClient, db_session: AsyncSession, platform, store, case, message):
    key = OTHER_KEY if case == "wrong_key" else PLATFORM_KEY

    def claims_fn(nonce):
        now = int(time.time())
        changes = {
            "wrong_nonce": {"nonce": "attacker"},
            "wrong_audience": {"aud": "someone-else"},
            "wrong_issuer": {"iss": "https://evil.example"},
            "expired": {"iat": now - 7200, "exp": now - 3600},
            "multi_aud_without_azp": {"aud": [CLIENT_ID, "other-tool"]},
            "lti_1_1": {LTI + "version": "1.1"},
            "deep_linking": {LTI + "message_type": "LtiDeepLinkingRequest"},
            "unknown_deployment": {LTI + "deployment_id": "dep-unknown"},
        }.get(case, {})
        claims = {**claims_for(nonce), **changes}
        if case == "no_context":
            del claims[LTI + "context"]
        return claims

    resp = await launch(client, key=key, claims_fn=claims_fn)
    assert resp.status_code == 400
    assert message in html.unescape(resp.text)
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_state_is_single_use(client: AsyncClient, platform, store):
    state, nonce = await start_login(client)
    id_token = jwt.encode(claims_for(nonce), PLATFORM_KEY, algorithm="RS256")
    first = await client.post("/lti/launch", data={"id_token": id_token, "state": state})
    assert first.status_code == 303
    replay = await client.post("/lti/launch", data={"id_token": id_token, "state": state})
    assert replay.status_code == 400
    assert "expired or was already used" in replay.text


async def test_unknown_state_is_refused(client: AsyncClient, platform, store):
    resp = await client.post("/lti/launch", data={"id_token": "x", "state": "never-issued"})
    assert resp.status_code == 400


# ── JWKS ─────────────────────────────────────────────────────────────────────

async def test_jwks_publishes_tool_keys(client: AsyncClient, platform):
    keys = (await client.get("/lti/jwks")).json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kid"] == "tool-kid"
    assert keys[0]["kty"] == "RSA" and keys[0]["alg"] == "RS256" and keys[0]["use"] == "sig"
    assert "d" not in keys[0]  # never the private part
