"""Resolver interface: turn an identifier into candidates, or re-fetch a bound record."""
import asyncio
from dataclasses import dataclass, field

import httpx

from app.ingest.candidate import Candidate, SourceError
from app.ingest.identifiers import Identifier
from app.ingest.sources import Source


@dataclass
class ResolveContext:
    http: httpx.AsyncClient
    sources: dict[str, Source] = field(default_factory=dict)
    # Per-source concurrency limits, created on first use (per context, so per event loop)
    _limits: dict[str, asyncio.Semaphore] = field(default_factory=dict, repr=False)

    def limit(self, name: str, slots: int) -> asyncio.Semaphore:
        if name not in self._limits:
            self._limits[name] = asyncio.Semaphore(slots)
        return self._limits[name]


class Resolver:
    """One source of candidates. Subclasses set `system` and override what they support."""

    system: str = ""

    def available(self, ctx: ResolveContext) -> bool:
        """False when the org hasn't configured what this resolver needs."""
        return True

    async def resolve(self, ident: Identifier, ctx: ResolveContext) -> list[Candidate]:
        """Candidates for an identifier; [] when this resolver doesn't handle it or finds nothing."""
        return []

    async def fetch(self, source_identifier: str, ctx: ResolveContext) -> Candidate | None:
        """The current record for a binding made earlier, or None if it no longer exists."""
        return None


async def get_json(
    ctx: ResolveContext, source: str, url: str, *, params=None, headers=None, not_found=(404,)
) -> dict | None:
    """GET a JSON document. None for "not found"; SourceError for anything else that fails."""
    try:
        resp = await ctx.http.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SourceError(source, f"could not be reached ({type(exc).__name__})") from exc
    if resp.status_code in not_found:
        return None
    if resp.status_code in (401, 403):
        raise SourceError(source, "rejected the API key")
    if resp.status_code == 429:
        raise SourceError(source, "is rate-limiting requests; try again shortly")
    if resp.status_code >= 400:
        raise SourceError(source, f"returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError(source, "returned a response that isn't JSON") from exc
