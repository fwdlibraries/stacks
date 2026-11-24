from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import User
from app.schemas.auth import CurrentUser, LoginRequest, RefreshRequest, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter()


def _issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=AuthService.create_token(user, "access"),
        refresh_token=AuthService.create_token(user, "refresh"),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/local/login", response_model=TokenResponse, summary="Local email/password login")
async def local_login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email and password. Returns access + refresh tokens."""
    user = await AuthService.authenticate(body.email, body.password, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
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
    """Return the current authenticated user."""
    return await db.scalar(
        select(User).where(User.id == current_user.id).options(selectinload(User.organization))
    )


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
