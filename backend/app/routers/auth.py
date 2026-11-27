import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import AuthSession, SsoConfig, User
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
from app.services.auth_service import AuthService, TokenPair
from app.services.ephemeral import EphemeralStore, get_ephemeral_store

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


# ── Where the refresh token goes ─────────────────────────────────────────────
#
# Stacks in its own tab asks for the refresh token as an HttpOnly cookie (header
# X-Stacks-Refresh: cookie), so page scripts never see it; the access token lives only
# in memory. Inside an LMS frame, browsers often block cookies, so the frontend takes
# the refresh token in the response body instead and keeps it for that tab only.
# The cookie is SameSite=Strict and only sent to /api/v1/auth, and refreshing from it
# needs the custom header too, which other sites can't send without CORS approval.

REFRESH_COOKIE = "stacks_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
REFRESH_HEADER = "x-stacks-refresh"


def wants_cookie(request: Request) -> bool:
    return request.headers.get(REFRESH_HEADER, "").lower() == "cookie"


def _set_refresh_cookie(request: Request, response: Response, token: str) -> None:
    host = (request.url.hostname or "").lower()
    response.set_cookie(
        REFRESH_COOKIE, token,
        max_age=settings.refresh_token_expire_days * 86400,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="strict",
        # Plain http is only for local development
        secure=host not in ("localhost", "127.0.0.1"),
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, samesite="strict")


def _tokens(pair: TokenPair, request: Request, response: Response) -> TokenResponse:
    refresh = pair.refresh_token
    if wants_cookie(request):
        _set_refresh_cookie(request, response, refresh)
        refresh = None
    return TokenResponse(
        access_token=pair.access_token, refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def _issue_tokens(
    db: AsyncSession, user: User, method: str, request: Request, response: Response
) -> TokenResponse:
    """Start a session (method: password / sso / lti) and return its tokens."""
    return _tokens(await AuthService.start_session(db, user, method), request, response)


def _failures_key(email: str) -> str:
    # Hashed: no email addresses in Redis keys
    return "login-failures:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


@router.post("/local/login", response_model=TokenResponse, summary="Local email/password login")
async def local_login(
    body: LoginRequest,
    request: Request,
    response: Response,
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
    return await _issue_tokens(db, user, "password", request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout")
async def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """End this sign-in: its access and refresh tokens stop working at once. Works with
    an expired access token, or with only the refresh cookie, so signing out never fails
    for that reason."""
    session = await AuthService.session_of(db, credentials.credentials) if credentials else None
    if session is None and (cookie := request.cookies.get(REFRESH_COOKIE)):
        session = await AuthService.session_of_refresh(db, cookie)
    if session is not None:
        await AuthService.revoke(db, session, "logout")
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


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
async def refresh_token(
    request: Request, response: Response, body: RefreshRequest | None = None, db: AsyncSession = Depends(get_db),
):
    """Exchange a refresh token (in the body, or the refresh cookie with
    X-Stacks-Refresh: cookie) for a new pair. Each refresh token works once: using an
    old one again ends the session (it was copied)."""
    token = body.refresh_token if body and body.refresh_token else None
    if token is None and wants_cookie(request):
        token = request.cookies.get(REFRESH_COOKIE)
    result = await AuthService.refresh(db, token) if token else None
    if result is None or not result[0].is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return _tokens(result[1], request, response)


@router.post("/lti/exchange", response_model=LtiExchangeResponse, summary="Exchange an LTI login code")
async def exchange_lti_code(
    body: LtiCodeExchange,
    request: Request,
    response: Response,
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
    tokens = await _issue_tokens(db, user, record.get("method", "lti"), request, response)
    return LtiExchangeResponse(**tokens.model_dump(), next=record["next"])


# ── Your sign-ins ────────────────────────────────────────────────────────────


class SessionOut(BaseModel):
    id: uuid.UUID
    method: str
    created_at: datetime
    last_used_at: datetime | None
    current: bool


async def _current_session_id(db: AsyncSession, credentials: HTTPAuthorizationCredentials | None) -> uuid.UUID | None:
    session = await AuthService.session_of(db, credentials.credentials) if credentials else None
    return session.id if session else None


@router.get("/sessions", response_model=list[SessionOut], summary="Where you're signed in")
async def list_sessions(
    user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    current = await _current_session_id(db, credentials)
    rows = await db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
               AuthSession.expires_at > datetime.now(UTC))
        .order_by(AuthSession.last_used_at.desc().nulls_last())
    )
    return [SessionOut(id=s.id, method=s.method, created_at=s.created_at, last_used_at=s.last_used_at,
                       current=s.id == current) for s in rows]


@router.post("/sessions/sign-out-others", summary="Sign out everywhere else")
async def sign_out_others(
    user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    current = await _current_session_id(db, credentials)
    return {"signed_out": await AuthService.revoke_all(db, user.id, "signed_out_elsewhere", except_id=current)}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="End one sign-in")
async def end_session(session_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await db.get(AuthSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await AuthService.revoke(db, session, "signed_out_elsewhere")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
