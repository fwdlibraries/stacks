"""Open Library: book metadata for ISBNs. Fallback when the library doesn't hold the book."""
import re

from app.ingest.candidate import Candidate
from app.ingest.draft import CitationDraft
from app.ingest.identifiers import Identifier, normalize_isbn
from app.ingest.resolvers.base import ResolveContext, Resolver, get_json
from app.ingest.resolvers.crossref import user_agent

API = "https://openlibrary.org/api/books"


def to_draft(book: dict, isbn: str) -> CitationDraft:
    year = re.search(r"\d{4}", book.get("publish_date") or "")
    title = ": ".join(t for t in (book.get("title"), book.get("subtitle")) if t)
    return CitationDraft(
        title=title or None,
        resource_type="book",
        author=[a["name"] for a in book.get("authors") or [] if a.get("name")],
        year=int(year.group()) if year else None,
        publisher=(book.get("publishers") or [{}])[0].get("name"),
        place_of_publication=(book.get("publish_places") or [{}])[0].get("name"),
        isbn=isbn,
    )


class OpenLibraryResolver(Resolver):
    system = "openlibrary"

    async def resolve(self, ident: Identifier, ctx: ResolveContext) -> list[Candidate]:
        if ident.kind != "isbn":
            return []
        candidate = await self.fetch(ident.value, ctx)
        return [candidate] if candidate else []

    async def fetch(self, source_identifier: str, ctx: ResolveContext) -> Candidate | None:
        if normalize_isbn(source_identifier) != source_identifier:
            return None
        key = f"ISBN:{source_identifier}"
        data = await get_json(
            ctx,
            "Open Library",
            API,
            params={"bibkeys": key, "format": "json", "jscmd": "data"},
            headers={"User-Agent": user_agent()},
        )
        book = (data or {}).get(key)
        if not book:
            return None
        return Candidate(
            draft=to_draft(book, source_identifier),
            source_system=self.system,
            source_identifier=source_identifier,
            match_method="identifier",
            # ISBNs are exact, but Open Library's records are crowd-edited
            confidence=0.9,
            raw=book,
        )
