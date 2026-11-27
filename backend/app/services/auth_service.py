"""Local authentication: password hashing, JWT issuing/validation, permission checks."""
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from passlib.context import CryptContext
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import AuthSession, User

logger = logging.getLogger(__name__)

TokenType = Literal["access", "refresh"]

# Two tabs can refresh with the same token at once; the slower one gets new tokens
# instead of revoking the session, if it's this soon after the rotation
REFRESH_GRACE = timedelta(seconds=30)


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str

# bcrypt only uses the first 72 bytes of a password; bcrypt>=5 raises instead of truncating
BCRYPT_MAX_BYTES = 72

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class PasswordTooLongError(ValueError):
    pass


class AuthService:
    # ── Passwords ────────────────────────────────────────────────────────────

    @staticmethod
    def hash_password(password: str) -> str:
        if len(password.encode()) > BCRYPT_MAX_BYTES:
            raise PasswordTooLongError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes")
        return _pwd_context.hash(password)

    @staticmethod
    def verify_password(password: str, password_hash: str | None) -> bool:
        if not password_hash or len(password.encode()) > BCRYPT_MAX_BYTES:
            return False
        try:
            return _pwd_context.verify(password, password_hash)
        except ValueError:
            # Malformed hash in the database
            logger.warning("Unverifiable password hash encountered")
            return False

    # ── Tokens and sessions ──────────────────────────────────────────────────
    #
    # Every sign-in is an AuthSession. Both tokens carry its id (`sid`), and the
    # refresh token also carries the session's generation (`gen`). Refreshing moves
    # the session to the next generation and returns a new pair. A refresh token from
    # an older generation has been used already, so someone copied it: the session is
    # revoked. (Two tabs refreshing at the same moment get a short grace instead.)

    @staticmethod
    def create_token(user: User, token_type: TokenType, session: AuthSession) -> str:
        now = datetime.now(UTC)
        lifetime = (
            timedelta(minutes=settings.access_token_expire_minutes)
            if token_type == "access"
            else timedelta(days=settings.refresh_token_expire_days)
        )
        claims = {
            "sub": str(user.id),
            "type": token_type,
            "sid": str(session.id),
            "iat": now,
            "exp": now + lifetime,
            "jti": uuid.uuid4().hex,
        }
        if token_type == "refresh":
            claims["gen"] = session.generation
        return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)

    @staticmethod
    def decode_token(token: str, expected_type: TokenType, *, verify_exp: bool = True) -> dict | None:
        try:
            claims = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm],
                options={"require": ["sub", "type", "sid", "iat", "exp"], "verify_exp": verify_exp},
            )
        except jwt.PyJWTError:
            return None
        if claims.get("type") != expected_type:
            return None
        return claims

    @staticmethod
    def _pair(user: User, session: AuthSession) -> TokenPair:
        return TokenPair(
            access_token=AuthService.create_token(user, "access", session),
            refresh_token=AuthService.create_token(user, "refresh", session),
        )

    @staticmethod
    async def start_session(db: AsyncSession, user: User, method: str) -> TokenPair:
        """A new sign-in for `user` (method: password / sso / lti), and its tokens."""
        now = datetime.now(UTC)
        session = AuthSession(
            user_id=user.id, method=method, last_used_at=now,
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
        db.add(session)
        await db.flush()
        return AuthService._pair(user, session)

    @staticmethod
    async def _session(db: AsyncSession, claims: dict) -> AuthSession | None:
        try:
            session_id = uuid.UUID(claims["sid"])
        except (KeyError, ValueError):
            return None
        session = await db.get(AuthSession, session_id)
        if session is None or str(session.user_id) != claims["sub"]:
            return None
        return session

    @staticmethod
    def _is_live(session: AuthSession) -> bool:
        return session.revoked_at is None and session.expires_at > datetime.now(UTC)

    @staticmethod
    async def refresh(db: AsyncSession, refresh_token: str) -> tuple[User, TokenPair] | None:
        """A new token pair for a valid refresh token, or None (sign in again)."""
        claims = AuthService.decode_token(refresh_token, "refresh")
        if claims is None or not isinstance(claims.get("gen"), int):
            return None
        session = await AuthService._session(db, claims)
        if session is None or not AuthService._is_live(session):
            return None
        user = await AuthService._valid_user(db, claims)
        if user is None:
            return None
        now = datetime.now(UTC)
        if claims["gen"] == session.generation:
            session.generation += 1
            session.rotated_at = now
        elif not (
            claims["gen"] == session.generation - 1
            and session.rotated_at is not None
            and now - session.rotated_at < REFRESH_GRACE
        ):
            # An old refresh token: someone else has (or had) a copy
            await AuthService.revoke(db, session, "reuse")
            logger.warning("Refresh token reuse; session %s revoked", session.id)
            return None
        session.last_used_at = now
        session.expires_at = now + timedelta(days=settings.refresh_token_expire_days)
        await db.flush()
        return user, AuthService._pair(user, session)

    @staticmethod
    async def revoke(db: AsyncSession, session: AuthSession, reason: str) -> None:
        if session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = reason
            await db.flush()

    @staticmethod
    async def revoke_all(
        db: AsyncSession, user_id: uuid.UUID, reason: str, *, except_id: uuid.UUID | None = None
    ) -> int:
        """Revoke every live session of a user (but `except_id`). Returns how many."""
        query = (
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        if except_id is not None:
            query = query.where(AuthSession.id != except_id)
        result = await db.execute(query)
        return result.rowcount or 0

    @staticmethod
    async def session_of(db: AsyncSession, access_token: str) -> AuthSession | None:
        """The session an access token belongs to, even if the token has expired
        (for logout)."""
        claims = AuthService.decode_token(access_token, "access", verify_exp=False)
        return await AuthService._session(db, claims) if claims else None

    @staticmethod
    async def session_of_refresh(db: AsyncSession, refresh_token: str) -> AuthSession | None:
        """The session a refresh token belongs to (for logout with only the cookie)."""
        claims = AuthService.decode_token(refresh_token, "refresh", verify_exp=False)
        return await AuthService._session(db, claims) if claims else None

    @staticmethod
    async def _valid_user(db: AsyncSession, claims: dict) -> User | None:
        try:
            user_id = uuid.UUID(claims["sub"])
        except ValueError:
            return None
        user = await db.get(User, user_id)
        if user is None:
            return None
        # Changing the password invalidates every token issued before the change
        if user.password_changed_at is not None:
            issued_at = datetime.fromtimestamp(claims["iat"], UTC)
            if issued_at < user.password_changed_at.replace(microsecond=0):
                return None
        return user

    @staticmethod
    async def get_user_from_token(token: str, db: AsyncSession) -> User | None:
        """The user an access token belongs to, if its session is still live."""
        claims = AuthService.decode_token(token, "access")
        if claims is None:
            return None
        session = await AuthService._session(db, claims)
        if session is None or not AuthService._is_live(session):
            return None
        return await AuthService._valid_user(db, claims)

    # ── Login ────────────────────────────────────────────────────────────────

    @staticmethod
    async def authenticate(
        email: str, password: str, db: AsyncSession, organization_id: uuid.UUID | None = None
    ) -> User | None:
        """Return the active local user for these credentials, or None.

        `organization_id` (from the request's hostname) limits sign-in to that
        organization's users, so the same email can exist at several schools.
        """
        query = select(User).where(func.lower(User.email) == email.strip().lower(), User.password_hash.is_not(None))
        if organization_id is not None:
            query = query.where(User.organization_id == organization_id)
        candidates = (await db.scalars(query)).all()
        if len(candidates) > 1:
            # Emails aren't unique across organizations; refuse rather than guess
            logger.warning("Local login matched %d users for one email; refusing", len(candidates))
            return None
        user = candidates[0] if candidates else None
        if user is None:
            # Spend comparable time to avoid revealing which emails exist
            _pwd_context.dummy_verify()
            return None
        if not AuthService.verify_password(password, user.password_hash) or not user.is_active:
            return None
        return user

    # ── Authorization ────────────────────────────────────────────────────────
