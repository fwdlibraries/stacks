from typing import AsyncIterator
import httpx

from app.importers.base import ImportHandler, RawRecord, CitationDraft


class ManualEntryHandler(ImportHandler):
    """
    Manual citation entry with optional metadata enrichment.

    When a DOI or ISBN is provided, attempts to enrich the record
    from CrossRef (DOI) or Open Library (ISBN) before presenting
    to the user for review.

    Payload shape:
    {
        "title": "...",          # required if no doi/isbn
        "doi": "10.xxxx/...",   # triggers CrossRef lookup
        "isbn": "978...",       # triggers Open Library lookup
        "resource_type": "book",
        # ... any other known fields
    }
    """

    CROSSREF_BASE = "https://api.crossref.org/works/"
    OPEN_LIBRARY_BASE = "https://openlibrary.org/api/books"
    USER_AGENT = "Stacks/0.1 (https://github.com/CSP-Library/stacks; mailto:admin@example.com)"

    async def fetch(self, payload: dict) -> AsyncIterator[RawRecord]:
        enriched = dict(payload)

        if doi := payload.get("doi"):
            crossref_data = await self._lookup_doi(doi)
            if crossref_data:
                # Merge: payload fields take precedence over enrichment
                enriched = {**crossref_data, **{k: v for k, v in payload.items() if v}}

        elif isbn := payload.get("isbn"):
            ol_data = await self._lookup_isbn(isbn)
            if ol_data:
                enriched = {**ol_data, **{k: v for k, v in payload.items() if v}}

        yield RawRecord(data=enriched, source="manual")

    def normalize(self, raw: RawRecord) -> CitationDraft:
        data = raw.data
        return CitationDraft(
            title=data.get("title"),
            resource_type=data.get("resource_type", "other"),
            author=self._parse_authors(data.get("author", [])),
            year=self._parse_year(data.get("year")),
            publisher=data.get("publisher"),
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

    async def _lookup_doi(self, doi: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.CROSSREF_BASE}{doi}",
                    headers={"User-Agent": self.USER_AGENT},
                )
                if response.status_code != 200:
                    return None
                work = response.json()["message"]
                return {
                    "title": work.get("title", [None])[0],
                    "author": [
                        f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
                        for a in work.get("author", [])
                    ],
                    "year": (work.get("published", {}).get("date-parts") or [[None]])[0][0],
                    "doi": work.get("DOI"),
                    "issn": (work.get("ISSN") or [None])[0],
                    "publisher": work.get("publisher"),
                    "resource_type": self._map_crossref_type(work.get("type", "")),
                    "metadata": {
                        "journal_name": (work.get("container-title") or [None])[0],
                    },
                }
        except Exception:
            return None

    async def _lookup_isbn(self, isbn: str) -> dict | None:
        clean_isbn = isbn.replace("-", "").replace(" ", "")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    self.OPEN_LIBRARY_BASE,
                    params={
                        "bibkeys": f"ISBN:{clean_isbn}",
                        "format": "json",
                        "jscmd": "data",
                    },
                    headers={"User-Agent": self.USER_AGENT},
                )
                if response.status_code != 200:
                    return None
                data = response.json()
                book = data.get(f"ISBN:{clean_isbn}")
                if not book:
                    return None
                return {
                    "title": book.get("title"),
                    "author": [a.get("name", "") for a in book.get("authors", [])],
                    "year": self._extract_year(book.get("publish_date", "")),
                    "publisher": (book.get("publishers") or [{}])[0].get("name"),
                    "isbn": clean_isbn,
                    "resource_type": "book",
                }
        except Exception:
            return None

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

    def _extract_year(self, date_str: str) -> int | None:
        digits = "".join(c for c in date_str if c.isdigit())
        if len(digits) >= 4:
            try:
                return int(digits[:4])
            except ValueError:
                pass
        return None

    def _map_crossref_type(self, crossref_type: str) -> str:
        mapping = {
            "journal-article": "journal_article",
            "book": "book",
            "book-chapter": "book_chapter",
            "monograph": "book",
            "proceedings-article": "other",
            "dataset": "other",
        }
        return mapping.get(crossref_type, "other")
