"""Local authentication: password hashing, JWT issuing/validation, permission checks."""
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import User

logger = logging.getLogger(__name__)

TokenType = Literal["access", "refresh"]

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

    # ── Tokens ───────────────────────────────────────────────────────────────

    @staticmethod
    def create_token(user: User, token_type: TokenType) -> str:
        now = datetime.now(UTC)
        lifetime = (
            timedelta(minutes=settings.access_token_expire_minutes)
            if token_type == "access"
            else timedelta(days=settings.refresh_token_expire_days)
        )
        claims = {
            "sub": str(user.id),
            "type": token_type,
            "iat": now,
            "exp": now + lifetime,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)

    @staticmethod
    def decode_token(token: str, expected_type: TokenType) -> dict | None:
        try:
            claims = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm],
                options={"require": ["sub", "type", "iat", "exp"]},
            )
        except jwt.PyJWTError:
            return None
        if claims.get("type") != expected_type:
            return None
        return claims

    @staticmethod
    async def get_user_from_token(
        token: str, db: AsyncSession, expected_type: TokenType = "access"
    ) -> User | None:
        claims = AuthService.decode_token(token, expected_type)
        if claims is None:
            return None
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

    # ── Login ────────────────────────────────────────────────────────────────

    @staticmethod
    async def authenticate(email: str, password: str, db: AsyncSession) -> User | None:
        """Return the active local user for these credentials, or None."""
        candidates = (
            await db.scalars(
                select(User).where(
                    func.lower(User.email) == email.strip().lower(),
                    User.password_hash.is_not(None),
                )
            )
        ).all()
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
