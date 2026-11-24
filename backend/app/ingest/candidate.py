"""A proposed citation from some source, with where it came from and how sure we are."""
from dataclasses import dataclass, field

from app.ingest.draft import CitationDraft

# Systems whose metadata is authoritative: citations bound to them are read-only
# in Stacks and kept in sync with the source record.
AUTHORITATIVE_SOURCES = frozenset({"alma"})


@dataclass
class Candidate:
    draft: CitationDraft
    source_system: str            # 'alma' | 'crossref' | 'openlibrary' | ...
    source_identifier: str        # MMS ID, DOI, ISBN: enough to fetch the record again
    match_method: str             # 'identifier' (exact) | 'search' | later 'ai'
    confidence: float             # 0.0–1.0
    raw: dict = field(default_factory=dict)  # kept as raw_import_data

    @property
    def authoritative(self) -> bool:
        return self.source_system in AUTHORITATIVE_SOURCES


class SourceError(Exception):
    """A source couldn't be queried (network, auth, quota). Reported, not fatal."""

    def __init__(self, source: str, message: str):
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message
