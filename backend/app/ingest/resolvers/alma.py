"""Alma: the library's authoritative bibliographic records (Bibs API)."""
import logging

from app.ingest import marc
from app.ingest.candidate import Candidate, SourceError
from app.ingest.draft import NormalizationError
from app.ingest.identifiers import Identifier
from app.ingest.resolvers import primo
from app.ingest.resolvers.base import ResolveContext, Resolver, get_json

logger = logging.getLogger(__name__)

# Several records can share an ISBN (print/electronic, editions); offer a few
MAX_ISBN_MATCHES = 5


class AlmaResolver(Resolver):
    system = "alma"

    def available(self, ctx: ResolveContext) -> bool:
        return "alma" in ctx.sources

    async def resolve(self, ident: Identifier, ctx: ResolveContext) -> list[Candidate]:
        if not self.available(ctx):
            return []
        if ident.kind == "mms_id":
            candidate = await self.fetch(ident.value, ctx)
            return [candidate] if candidate else []
        if ident.kind == "isbn" and primo.available(ctx):
            return await self._by_isbn(ident.value, ctx)
        return []

    async def _by_isbn(self, isbn: str, ctx: ResolveContext) -> list[Candidate]:
        docs = await primo.search(ctx, f"isbn,exact,{isbn}", limit=MAX_ISBN_MATCHES, local_only=True)
        candidates = []
        for mms_id in dict.fromkeys(m for d in docs if (m := primo.mms_id(d))):
            if candidate := await self.fetch(mms_id, ctx):
                candidate.match_method = "isbn"
                # Exact identifier, but may be another edition or format of the same work
                candidate.confidence = 0.95
                candidates.append(candidate)
        return candidates

    async def fetch(self, source_identifier: str, ctx: ResolveContext) -> Candidate | None:
        if not self.available(ctx):
            raise SourceError("Alma", "is not configured for this organization")
        if not source_identifier.isdigit():
            return None
        source = ctx.sources["alma"]
        bib = await get_json(
            ctx,
            "Alma",
            f"{source.config.api_base}/almaws/v1/bibs/{source_identifier}",
            params={"view": "full"},
            headers={"Authorization": f"apikey {source.api_key}", "Accept": "application/json"},
            # Alma answers an unknown or malformed MMS ID with HTTP 400 rather than 404
            not_found=(400, 404),
        )
        return bib_to_candidate(bib, source_identifier) if bib and bib.get("anies") else None


def bib_to_candidate(bib: dict, mms_id: str | None = None) -> Candidate:
    """An Alma Bibs API record (JSON with MARC XML in `anies`) as a candidate."""
    try:
        draft = marc.to_draft(marc.parse_marcxml(bib["anies"][0]))
    except NormalizationError as exc:
        raise SourceError("Alma", f"returned a record Stacks can't read ({exc})") from exc
    return Candidate(
        draft=draft,
        source_system="alma",
        source_identifier=bib.get("mms_id") or mms_id or "",
        match_method="identifier",
        confidence=1.0,
        raw={k: bib.get(k) for k in ("mms_id", "suppress_from_publishing", "record_format", "anies")},
    )


def is_suppressed(bib_raw: dict) -> bool:
    """Hidden from discovery: students can't find it in Primo."""
    return str(bib_raw.get("suppress_from_publishing", "")).lower() == "true"


async def fetch_many(mms_ids: list[str], ctx: ResolveContext) -> dict[str, Candidate | None]:
    """Full records for many MMS IDs, 100 per call. IDs Alma doesn't hold are absent.

    A record Stacks can't parse maps to None (and is logged): absent means "not
    found", so the sync only flags records Alma really lacks.
    """
    source = ctx.sources["alma"]
    found: dict[str, Candidate | None] = {}
    ids = [m for m in dict.fromkeys(mms_ids) if m.isdigit()]
    for start in range(0, len(ids), 100):
        chunk = ids[start : start + 100]
        data = await get_json(
            ctx,
            "Alma",
            f"{source.config.api_base}/almaws/v1/bibs",
            params={"mms_id": ",".join(chunk), "view": "full"},
            headers={"Authorization": f"apikey {source.api_key}", "Accept": "application/json"},
            not_found=(400, 404),
        )
        for bib in (data or {}).get("bib") or []:
            if not bib.get("anies") or not bib.get("mms_id"):
                continue
            try:
                found[bib["mms_id"]] = bib_to_candidate(bib)
            except SourceError:
                logger.warning("Alma record %s can't be parsed; leaving its citations unchanged", bib["mms_id"])
                found[bib["mms_id"]] = None
    return found


async def held(mms_ids: list[str], ctx: ResolveContext) -> set[str]:
    """Which of these MMS IDs the institution's Alma holds (one call per 100 IDs).

    Primo also shows consortium (Network Zone) records, which the institution's
    key can't read; those come back missing here.
    """
    source = ctx.sources["alma"]
    found: set[str] = set()
    ids = [m for m in dict.fromkeys(mms_ids) if m.isdigit()]
    for start in range(0, len(ids), 100):
        data = await get_json(
            ctx,
            "Alma",
            f"{source.config.api_base}/almaws/v1/bibs",
            params={"mms_id": ",".join(ids[start : start + 100]), "view": "brief"},
            headers={"Authorization": f"apikey {source.api_key}", "Accept": "application/json"},
            not_found=(400, 404),
        )
        found.update(b["mms_id"] for b in (data or {}).get("bib") or [] if b.get("mms_id"))
    return found
