"""The resolver chain, in priority order: the library's own system first."""
from app.ingest.resolvers.alma import AlmaResolver
from app.ingest.resolvers.base import ResolveContext, Resolver
from app.ingest.resolvers.crossref import CrossrefResolver
from app.ingest.resolvers.openlibrary import OpenLibraryResolver
from app.ingest.resolvers.primo import PrimoResolver

CHAIN: list[Resolver] = [AlmaResolver(), CrossrefResolver(), OpenLibraryResolver()]
# Everything a binding can point at; Primo (CDI) records come from search, not identifiers
BY_SYSTEM: dict[str, Resolver] = {r.system: r for r in [*CHAIN, PrimoResolver()]}

__all__ = ["BY_SYSTEM", "CHAIN", "ResolveContext", "Resolver"]
