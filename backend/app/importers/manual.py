import dataclasses
from collections.abc import AsyncIterator

import httpx

from app.importers.base import CitationDraft, ImportHandler, RawRecord
from app.ingest.candidate import SourceError
from app.ingest.identifiers import normalize_doi, normalize_isbn
from app.ingest.resolvers import ResolveContext
from app.ingest.resolvers.crossref import CrossrefResolver
from app.ingest.resolvers.openlibrary import OpenLibraryResolver


class ManualEntryHandler(ImportHandler):
    """
    Manual citation entry with optional metadata enrichment.

    When a DOI or ISBN is provided, attempts to enrich the record
    from CrossRef (DOI) or Open Library (ISBN) before presenting
    to the user for review. Payload fields take precedence.

    Payload shape:
    {
        "title": "...",          # required if no doi/isbn
        "doi": "10.xxxx/...",   # triggers CrossRef lookup
        "isbn": "978...",       # triggers Open Library lookup
        "resource_type": "book",
        # ... any other known fields
    }
    """

    async def fetch(self, payload: dict) -> AsyncIterator[RawRecord]:
        enriched = dict(payload)
        async with httpx.AsyncClient(timeout=10.0) as client:
            ctx = ResolveContext(http=client)
            candidate = None
            try:
                if (doi := normalize_doi(payload.get("doi") or "")):
                    candidate = await CrossrefResolver().fetch(doi, ctx)
                elif (isbn := normalize_isbn(payload.get("isbn") or "")):
                    candidate = await OpenLibraryResolver().fetch(isbn, ctx)
            except SourceError:
                candidate = None
        if candidate:
            found = {k: v for k, v in dataclasses.asdict(candidate.draft).items() if v}
            enriched = {**found, **{k: v for k, v in payload.items() if v}}
        yield RawRecord(data=enriched, source="manual")

    def normalize(self, raw: RawRecord) -> CitationDraft:
        data = raw.data
        return CitationDraft(
            title=data.get("title"),
            resource_type=data.get("resource_type", "other"),
            author=self._parse_authors(data.get("author", [])),
            editor=self._parse_authors(data.get("editor", [])),
            year=self._parse_year(data.get("year")),
            publisher=data.get("publisher"),
            place_of_publication=data.get("place_of_publication"),
            isbn=data.get("isbn"),
            issn=data.get("issn"),
            doi=data.get("doi"),
            url=data.get("url"),
            volume=data.get("volume"),
            issue=data.get("issue"),
            pages=data.get("pages"),
            student_note=data.get("student_note"),
            staff_note=data.get("staff_note"),
            metadata=data.get("metadata", {}),
        )

    def _parse_authors(self, authors) -> list[str]:
        if isinstance(authors, str):
            return [a.strip() for a in authors.split(";") if a.strip()]
        if isinstance(authors, list):
            return [str(a).strip() for a in authors if a]
        return []

    def _parse_year(self, year) -> int | None:
        if year is None:
            return None
        try:
            return int(str(year)[:4])
        except (ValueError, TypeError):
            return None
