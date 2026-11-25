"""Short-lived values in Redis: single-use ones (LTI state/nonce, one-time login
codes) and caches (resolved links).

Exposed as a FastAPI dependency (`get_ephemeral_store`) so tests can swap in
the in-memory implementation.
"""
import json
import time
from typing import Protocol

import redis.asyncio as aioredis

from app.config import settings


class EphemeralStore(Protocol):
    async def put(self, key: str, value: dict, ttl_seconds: int) -> None: ...

    async def get(self, key: str) -> dict | None:
        """Return the value without consuming it (for caches)."""
        ...

    async def pop(self, key: str) -> dict | None:
        """Return and delete the value, so each one can be used only once."""
        ...

    async def incr(self, key: str, ttl_seconds: int) -> int:
        """Add one to a counter that expires `ttl_seconds` after its first increment."""
        ...

    async def count(self, key: str) -> int:
        ...

    async def reset(self, key: str) -> None: ...


class RedisStore:
    def __init__(self, url: str):
        self._redis = aioredis.from_url(url)

    async def put(self, key: str, value: dict, ttl_seconds: int) -> None:
        await self._redis.set(key, json.dumps(value), ex=ttl_seconds)

    async def get(self, key: str) -> dict | None:
        raw = await self._redis.get(key)
        return json.loads(raw) if raw is not None else None

    async def pop(self, key: str) -> dict | None:
        raw = await self._redis.getdel(key)
        return json.loads(raw) if raw is not None else None

    async def incr(self, key: str, ttl_seconds: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl_seconds, nx=True)  # the window starts at the first one
            value, _ = await pipe.execute()
        return int(value)

    async def count(self, key: str) -> int:
        raw = await self._redis.get(key)
        return int(raw) if raw is not None else 0

    async def reset(self, key: str) -> None:
        await self._redis.delete(key)


class MemoryStore:
    """In-process store for tests."""

    def __init__(self):
        self._items: dict[str, tuple[float, dict]] = {}

    async def put(self, key: str, value: dict, ttl_seconds: int) -> None:
        self._items[key] = (time.monotonic() + ttl_seconds, value)

    async def get(self, key: str) -> dict | None:
        expires_at, value = self._items.get(key, (0.0, None))
        return value if value is not None and expires_at > time.monotonic() else None

    async def pop(self, key: str) -> dict | None:
        expires_at, value = self._items.pop(key, (0.0, None))
        return value if value is not None and expires_at > time.monotonic() else None

    async def incr(self, key: str, ttl_seconds: int) -> int:
        expires_at, value = self._items.get(key, (0.0, None))
        if value is None or expires_at <= time.monotonic():
            expires_at, value = time.monotonic() + ttl_seconds, {"n": 0}
        value = {"n": value["n"] + 1}
        self._items[key] = (expires_at, value)
        return value["n"]

    async def count(self, key: str) -> int:
        value = await self.get(key)
        return value["n"] if value else 0

    async def reset(self, key: str) -> None:
        self._items.pop(key, None)


_store: RedisStore | None = None


def get_ephemeral_store() -> EphemeralStore:
    global _store
    if _store is None:
        _store = RedisStore(settings.redis_url)
    return _store
