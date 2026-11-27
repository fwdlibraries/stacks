"""Sign-ins are server-side sessions: refresh tokens rotate, a reused refresh token ends
the session, and logout or an administrator ends it at once."""
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import AuthSession, ScopeType
from app.services import access
from tests.test_api.test_auth import login, make_user
from tests.test_api.test_permissions import World, sign_in


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def me(client: AsyncClient, token: str) -> int:
    return (await client.get("/api/v1/auth/me", headers=bearer(token))).status_code


async def refresh(client: AsyncClient, token: str):
    return await client.post("/api/v1/auth/token/refresh", json={"refresh_token": token})


@pytest.fixture
async def tokens(client: AsyncClient, db_session: AsyncSession) -> dict:
    await make_user(db_session)
    resp = await login(client)
    assert resp.status_code == 200
    return resp.json()


async def test_refresh_rotates_and_a_reused_token_ends_the_session(client, db_session, tokens):
    first = await refresh(client, tokens["refresh_token"])
    assert first.status_code == 200
    second = await refresh(client, first.json()["refresh_token"])
    assert second.status_code == 200

    # The first refresh token, used again later: someone copied it
    session = await db_session.scalar(select(AuthSession))
    session.rotated_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401

    await db_session.refresh(session)
    assert session.revoked_reason == "reuse"
    # Everything from that session stops working, including the newest tokens
    assert await me(client, second.json()["access_token"]) == 401
    assert (await refresh(client, second.json()["refresh_token"])).status_code == 401


async def test_two_tabs_refreshing_at_once_both_succeed(client, tokens):
    a = await refresh(client, tokens["refresh_token"])
    b = await refresh(client, tokens["refresh_token"])  # same token, moments later
    assert (a.status_code, b.status_code) == (200, 200)
    assert await me(client, b.json()["access_token"]) == 200
    assert (await refresh(client, a.json()["refresh_token"])).status_code == 200


async def test_logout_ends_the_session_even_with_an_expired_access_token(client, db_session, tokens):
    claims = jwt.decode(tokens["access_token"], settings.secret_key, algorithms=[settings.algorithm])
    expired = jwt.encode({**claims, "exp": datetime.now(UTC) - timedelta(minutes=1)},
                         settings.secret_key, algorithm=settings.algorithm)
    assert (await client.post("/api/v1/auth/logout", headers=bearer(expired))).status_code == 204
    assert await me(client, tokens["access_token"]) == 401
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401


async def test_tokens_without_a_session_are_refused(client, db_session, tokens):
    claims = jwt.decode(tokens["access_token"], settings.secret_key, algorithms=[settings.algorithm])
    del claims["sid"]
    old_style = jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)
    assert await me(client, old_style) == 401


async def test_list_sessions_and_sign_out_elsewhere(client, db_session, tokens):
    other = (await login(client)).json()
    sessions = (await client.get("/api/v1/auth/sessions", headers=bearer(tokens["access_token"]))).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    assert {s["method"] for s in sessions} == {"password"}

    resp = await client.post("/api/v1/auth/sessions/sign-out-others", headers=bearer(tokens["access_token"]))
    assert resp.json() == {"signed_out": 1}
    assert await me(client, other["access_token"]) == 401
    assert await me(client, tokens["access_token"]) == 200

    # Someone else's session can't be ended (or seen)
    stranger = await make_user(db_session, email="other@example.edu", slug="other-org")
    theirs = AuthSession(user_id=stranger.id, method="password", expires_at=datetime.now(UTC) + timedelta(days=1))
    db_session.add(theirs)
    await db_session.commit()
    resp = await client.delete(f"/api/v1/auth/sessions/{theirs.id}", headers=bearer(tokens["access_token"]))
    assert resp.status_code == 404


async def test_administrators_can_sign_people_out(client, db_session):
    world = await World().build(db_session)
    admin = await world.person(db_session, "admin", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    lib = await world.person(db_session, "lib", access.LIBRARIAN, (ScopeType.organization, world.org.id))
    await sign_in(client, lib)
    lib_token = client.headers.pop("Authorization").removeprefix("Bearer ")
    assert await me(client, lib_token) == 200

    # A librarian can't sign people out; an organization-wide administrator can
    await sign_in(client, lib)
    assert (await client.post(f"/api/v1/admin/people/{lib.id}/sign-out")).status_code == 403
    await sign_in(client, admin)
    resp = await client.post(f"/api/v1/admin/people/{lib.id}/sign-out")
    assert resp.status_code == 200 and resp.json()["signed_out"] == 2
    assert await me(client, lib_token) == 401

    # Turning an account off signs it out too
    await sign_in(client, admin)
    admin_token = client.headers["Authorization"].removeprefix("Bearer ")
    await sign_in(client, lib)
    lib_token = client.headers.pop("Authorization").removeprefix("Bearer ")
    resp = await client.patch(f"/api/v1/admin/people/{lib.id}", json={"is_active": False}, headers=bearer(admin_token))
    assert resp.status_code == 200, resp.text
    sid = jwt.decode(lib_token, settings.secret_key, algorithms=[settings.algorithm])["sid"]
    session = await db_session.get(AuthSession, uuid.UUID(sid))
    await db_session.refresh(session)
    assert session.revoked_reason == "account_off"
