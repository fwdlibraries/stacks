"""Entry points: look up what a list-builder pasted, and re-fetch a bound record."""
from dataclasses import dataclass, field

from app.ingest.candidate import Candidate, SourceError
from app.ingest.identifiers import Identifier, detect
from app.ingest.resolvers import BY_SYSTEM, CHAIN, ResolveContext, alma, primo

MAX_IDENTIFIERS = 5


@dataclass
class LookupResult:
    identifiers: list[Identifier] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def lookup(text: str, ctx: ResolveContext) -> LookupResult:
    """Candidates for every identifier in `text`.

    For each identifier the chain stops at the first resolver with results, so a
    record the library holds wins over open-data fallbacks. A source that fails
    adds a warning and the chain carries on.
    """
    result = LookupResult(identifiers=detect(text)[:MAX_IDENTIFIERS])
    seen: set[tuple[str, str]] = set()
    for ident in result.identifiers:
        for resolver in CHAIN:
            try:
                found = await resolver.resolve(ident, ctx)
            except SourceError as exc:
                if str(exc) not in result.warnings:
                    result.warnings.append(str(exc))
                continue
            for candidate in found:
                key = (candidate.source_system, candidate.source_identifier)
                if key not in seen:
                    seen.add(key)
                    result.candidates.append(candidate)
            if found:
                break
    result.candidates.sort(key=lambda c: (not c.authoritative, -c.confidence))
    return result


async def fetch(source_system: str, source_identifier: str, ctx: ResolveContext) -> Candidate | None:
    """The current record behind a binding. Raises SourceError if the source can't be asked."""
    resolver = BY_SYSTEM.get(source_system)
    if resolver is None:
        raise SourceError(source_system, "is not a source Stacks can import from")
    candidate = await resolver.fetch(source_identifier, ctx) if resolver.available(ctx) else None
    if candidate is None and source_system == "alma" and primo.available(ctx):
        # Not in the institution's Alma (e.g. a consortium Network Zone record):
        # use Primo's copy, which is not kept in sync
        candidate = await BY_SYSTEM["primo"].fetch(f"alma{source_identifier}", ctx)
    return candidate


async def search(text: str, ctx: ResolveContext, *, offset: int = 0, limit: int = 10) -> tuple[int, list[Candidate]]:
    """Keyword search of the library's discovery system.

    Results the institution's Alma actually holds stay `alma` (bound and synced when
    added); other local records, such as consortium Network Zone ones, become
    Primo records so nothing promises a sync Stacks can't do.
    """
    total, candidates = await primo.search_candidates(ctx, text, offset=offset, limit=limit)
    return total, await reconcile_holdings(candidates, ctx)


async def reconcile_holdings(candidates: list[Candidate], ctx: ResolveContext) -> list[Candidate]:
    """Keep `alma` only for records the institution's Alma holds; others become Primo records."""
    alma_ids = [c.source_identifier for c in candidates if c.source_system == "alma"]
    if not alma_ids:
        return candidates
    held: set[str] = set()
    if "alma" in ctx.sources:
        try:
            held = await alma.held(alma_ids, ctx)
        except SourceError:
            held = set(alma_ids)  # can't tell: adding will fall back to Primo if needed
    for candidate in candidates:
        if candidate.source_system == "alma" and candidate.source_identifier not in held:
            candidate.source_system = "primo"
            candidate.source_identifier = f"alma{candidate.source_identifier}"
    return candidates
