import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import SsoConfig, User
from app.schemas.auth import (
    Capabilities,
    CurrentUser,
    LoginRequest,
    LtiCodeExchange,
    LtiExchangeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.services import tenancy
from app.services.access import load_grants
from app.services.auth_service import AuthService
from app.services.ephemeral import EphemeralStore, get_ephemeral_store

router = APIRouter()


def _issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=AuthService.create_token(user, "access"),
        refresh_token=AuthService.create_token(user, "refresh"),
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _failures_key(email: str) -> str:
    # Hashed: no email addresses in Redis keys
    return "login-failures:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


@router.post("/local/login", response_model=TokenResponse, summary="Local email/password login")
async def local_login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    store: EphemeralStore = Depends(get_ephemeral_store),
    tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant),
):
    """Authenticate with email and password. Returns access + refresh tokens.

    After LOGIN_MAX_FAILURES failed attempts for an email address, sign-in for it
    is paused (429) until LOGIN_LOCKOUT_MINUTES after the first failure. This is
    per account, whatever the IP; the proxy in front also limits per IP. Unknown
    addresses are counted the same way, so responses don't reveal which exist.
    """
    key = _failures_key(body.email)
    window = settings.login_lockout_minutes * 60
    if await store.count(key) >= settings.login_max_failures:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Try again in {settings.login_lockout_minutes} minutes.",
            headers={"Retry-After": str(window)},
        )
    # On an organization's own hostname, only its users can sign in there
    org_id = tenant.organization_id if tenant and tenant.by_domain else None
    user = await AuthService.authenticate(body.email, body.password, db, org_id)
    if user is None:
        await store.incr(key, window)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    await store.reset(key)
    # An organization that signs in through its identity provider can turn passwords off
    # (system admins keep theirs, as a way in if single sign-on breaks)
    if not user.is_system_admin and await db.scalar(
        select(SsoConfig.id).where(
            SsoConfig.organization_id == user.organization_id,
            SsoConfig.is_active.is_(True),
            SsoConfig.disable_passwords.is_(True),
        )
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Use your institution's sign-in for Stacks.")
    user.last_login_at = datetime.now(UTC)
    return _issue_tokens(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout")
async def logout() -> Response:
    """
    Tokens are stateless JWTs, so logout is client-side: the client discards them.
    Server-side revocation (a denylist keyed on `jti`) can be added later; changing
    the password already invalidates all earlier tokens.
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=CurrentUser, summary="Current user")
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return the current authenticated user, and what they may administer."""
    user = await db.scalar(select(User).where(User.id == current_user.id).options(selectinload(User.organization)))
    grants = await load_grants(db, current_user)
    user.can = Capabilities(
        manage_settings=grants.organization_wide("settings.manage"),
        manage_people=grants.anywhere("people.manage"),
        manage_courses=grants.anywhere("courses.manage"),
        view_reports=grants.anywhere("reports.view"),
    )
    return user


@router.post("/token/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access + refresh token pair."""
    user = await AuthService.get_user_from_token(body.refresh_token, db, expected_type="refresh")
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return _issue_tokens(user)


@router.post("/lti/exchange", response_model=LtiExchangeResponse, summary="Exchange an LTI login code")
async def exchange_lti_code(
    body: LtiCodeExchange,
    db: AsyncSession = Depends(get_db),
    store: EphemeralStore = Depends(get_ephemeral_store),
):
    """
    Swap the one-time code from an LTI launch redirect for tokens. Codes live for
    60 seconds and work once, so tokens never appear in URLs or browser history.
    """
    record = await store.pop(f"lti:code:{body.code}")
    user = await db.get(User, uuid.UUID(record["user_id"])) if record else None
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This sign-in link has expired. Open Stacks again from your course.",
        )
    user.last_login_at = datetime.now(UTC)
    return LtiExchangeResponse(**_issue_tokens(user).model_dump(), next=record["next"])
