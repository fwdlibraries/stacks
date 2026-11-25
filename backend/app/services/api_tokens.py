"""Personal tokens for clients that can't hold a browser session, like the browser
extension. Only the SHA-256 hash is stored; the token is shown once, at creation.
Each token has scopes, and endpoints accept a token only if it has their scope."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ApiKey, User

PREFIX = "stx_"
EXTENSION_SCOPE = "extension"
# Don't write last_used_at on every request
_TOUCH_EVERY = timedelta(minutes=15)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_token(value: str) -> bool:
    return value.startswith(PREFIX)


async def create(db: AsyncSession, user: User, name: str, scopes: list[str]) -> tuple[ApiKey, str]:
    token = PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(user_id=user.id, name=name, key_hash=_hash(token), key_prefix=token[:12], scopes=scopes)
    db.add(key)
    await db.flush()
    return key, token


async def user_for(db: AsyncSession, token: str, scope: str) -> User | None:
    """The active user behind a live token that has `scope`, else None."""
    key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == _hash(token)))
    now = datetime.now(UTC)
    if key is None or key.revoked_at is not None or scope not in (key.scopes or []):
        return None
    if key.expires_at is not None and key.expires_at <= now:
        return None
    user = await db.get(User, key.user_id)
    if user is None or not user.is_active:
        return None
    if key.last_used_at is None or now - key.last_used_at > _TOUCH_EVERY:
        key.last_used_at = now
    return user
