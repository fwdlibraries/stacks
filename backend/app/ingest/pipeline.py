"""Entry points: look up what a list-builder pasted, and re-fetch a bound record."""
from dataclasses import dataclass, field

from app.ingest.candidate import Candidate, SourceError
from app.ingest.identifiers import Identifier, detect
from app.ingest.resolvers import BY_SYSTEM, CHAIN, ResolveContext

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
    return await resolver.fetch(source_identifier, ctx)
