from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Organization, User
from app.services.auth_service import AuthService

PASSWORD = "correct horse battery staple"


async def make_user(db: AsyncSession, email="librarian@example.edu", slug="test-org", **kwargs) -> User:
    org = Organization(name=f"Org {slug}", slug=slug)
    user = User(
        organization=org,
        email=email,
        display_name="Test Librarian",
        password_hash=AuthService.hash_password(PASSWORD),
        **kwargs,
    )
    db.add(user)
    await db.commit()
    return user


async def login(client: AsyncClient, email="librarian@example.edu", password=PASSWORD):
    return await client.post("/api/v1/auth/local/login", json={"email": email, "password": password})


@pytest.mark.asyncio
async def test_login_returns_tokens_and_me_works(client: AsyncClient, db_session: AsyncSession):
    await make_user(db_session)

    resp = await login(client, email="  Librarian@Example.edu ")  # case/whitespace-insensitive
    assert resp.status_code == 200
    tokens = resp.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "librarian@example.edu"
    assert body["organization"]["slug"] == "test-org"
    assert "password_hash" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "email,password",
    [("librarian@example.edu", "wrong password"), ("nobody@example.edu", PASSWORD), ("librarian@example.edu", "x" * 100)],
)
async def test_bad_credentials_get_the_same_401(client: AsyncClient, db_session: AsyncSession, email, password):
    await make_user(db_session)
    resp = await login(client, email, password)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_inactive_user_cannot_log_in(client: AsyncClient, db_session: AsyncSession):
    await make_user(db_session, is_active=False)
    assert (await login(client)).status_code == 401


@pytest.mark.asyncio
async def test_me_requires_a_valid_access_token(client: AsyncClient, db_session: AsyncSession):
    await make_user(db_session)
    refresh = (await login(client)).json()["refresh_token"]

    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"})).status_code == 401
    # A refresh token is not an access token
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_issues_new_tokens_and_rejects_access_tokens(client: AsyncClient, db_session: AsyncSession):
    await make_user(db_session)
    tokens = (await login(client)).json()

    resp = await client.post("/api/v1/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200

    resp = await client.post("/api/v1/auth/token/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_password_change_invalidates_earlier_tokens(client: AsyncClient, db_session: AsyncSession):
    user = await make_user(db_session)
    tokens = (await login(client)).json()

    user.password_changed_at = datetime.now(UTC) + timedelta(seconds=2)
    await db_session.commit()

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 401
    resp = await client.post("/api/v1/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_email_across_orgs_is_refused(client: AsyncClient, db_session: AsyncSession):
    await make_user(db_session, slug="org-a")
    await make_user(db_session, slug="org-b")
    assert (await login(client)).status_code == 401


def test_password_hashing_limits():
    assert AuthService.verify_password(PASSWORD, AuthService.hash_password(PASSWORD))
    assert not AuthService.verify_password("x" * 100, AuthService.hash_password(PASSWORD))
    with pytest.raises(ValueError):
        AuthService.hash_password("x" * 73)



async def test_repeated_failures_pause_sign_in_for_that_account(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "login_max_failures", 3)
    db_session.add(
        User(organization=Organization(name="Org", slug="org-rl"), email="ada@example.edu",
             display_name="Ada", password_hash=AuthService.hash_password("correct horse battery"))
    )
    await db_session.commit()

    async def login(email, password):
        return await client.post("/api/v1/auth/local/login", json={"email": email, "password": password})

    for _ in range(3):
        assert (await login("ada@example.edu", "wrong password!")).status_code == 401
    paused = await login("ADA@example.edu", "correct horse battery")  # even the right password, any case
    assert paused.status_code == 429
    assert paused.headers["retry-after"] == str(settings.login_lockout_minutes * 60)

    # Other accounts are unaffected; unknown addresses are counted the same way
    for _ in range(3):
        assert (await login("nobody@example.edu", "wrong password!")).status_code == 401
    assert (await login("nobody@example.edu", "wrong password!")).status_code == 429


async def test_success_resets_the_count(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "login_max_failures", 3)
    db_session.add(
        User(organization=Organization(name="Org", slug="org-rl2"), email="bo@example.edu",
             display_name="Bo", password_hash=AuthService.hash_password("correct horse battery"))
    )
    await db_session.commit()
    for password in ("wrong one!!!", "wrong two!!!", "correct horse battery", "wrong 3!!!!!", "wrong 4!!!!!"):
        await client.post("/api/v1/auth/local/login", json={"email": "bo@example.edu", "password": password})
    ok = await client.post("/api/v1/auth/local/login", json={"email": "bo@example.edu", "password": "correct horse battery"})
    assert ok.status_code == 200
