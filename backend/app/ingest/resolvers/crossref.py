"""Crossref: metadata for DOIs. Open data; not the library's system, so not authoritative."""
import asyncio
from urllib.parse import quote

from app.config import settings
from app.ingest.candidate import Candidate, SourceError
from app.ingest.draft import CitationDraft
from app.ingest.identifiers import Identifier, normalize_doi, normalize_isbn
from app.ingest.resolvers.base import ResolveContext, Resolver, get_json

API = "https://api.crossref.org/works/"

TYPES = {
    "journal-article": "journal_article",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "reference-book": "book",
    "book-chapter": "book_chapter",
    "book-section": "book_chapter",
    "book-part": "book_chapter",
}


def user_agent(ctx: ResolveContext | None = None) -> str:
    # Crossref asks for a contact address (its "polite pool"); only send one if configured
    email = (ctx and ctx.contact_email) or settings.metadata_contact_email
    contact = f"; mailto:{email}" if email else ""
    return f"Stacks/0.1 (https://github.com/fwdlibraries/stacks{contact})"


def _names(people: list[dict] | None) -> list[str]:
    names = []
    for person in people or []:
        if family := person.get("family"):
            names.append(f"{family}, {person['given']}" if person.get("given") else family)
        elif person.get("name"):
            names.append(person["name"])
    return names


def _year(work: dict) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = (work.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def to_draft(work: dict) -> CitationDraft:
    rtype = TYPES.get(work.get("type", ""), "other")
    container = (work.get("container-title") or [None])[0]
    metadata = {}
    if container:
        metadata["journal_name" if rtype == "journal_article" else "container_title"] = container
    isbns = [i for raw in work.get("ISBN") or [] if (i := normalize_isbn(raw))]
    return CitationDraft(
        title=": ".join(t for t in [(work.get("title") or [None])[0], (work.get("subtitle") or [None])[0]] if t)
        or None,
        resource_type=rtype,
        author=_names(work.get("author")),
        editor=_names(work.get("editor")),
        year=_year(work),
        publisher=work.get("publisher"),
        volume=work.get("volume"),
        issue=work.get("issue"),
        pages=work.get("page"),
        isbn=isbns[0] if isbns else None,
        issn=(work.get("ISSN") or [None])[0],
        doi=normalize_doi(work.get("DOI") or ""),
        metadata=metadata,
    )


class CrossrefResolver(Resolver):
    system = "crossref"

    async def resolve(self, ident: Identifier, ctx: ResolveContext) -> list[Candidate]:
        if ident.kind != "doi":
            return []
        candidate = await self.fetch(ident.value, ctx)
        return [candidate] if candidate else []

    async def fetch(self, source_identifier: str, ctx: ResolveContext) -> Candidate | None:
        if normalize_doi(source_identifier) != source_identifier.lower() or ".." in source_identifier:
            return None
        data = await get_json(
            ctx, "Crossref", API + quote(source_identifier, safe="/"), headers={"User-Agent": user_agent(ctx)}
        )
        work = (data or {}).get("message")
        if not work:
            return None
        return Candidate(
            draft=to_draft(work),
            source_system=self.system,
            source_identifier=source_identifier,
            match_method="identifier",
            confidence=1.0,
            raw=work,
        )


# Crossref's public pool rate-limits bursts (more so without METADATA_CONTACT_EMAIL);
# bulk imports match several entries at once, so searches go one at a time
SEARCH_SLOTS = 1
RETRY_DELAYS = (1.5, 3.0)


async def search_bibliographic(text: str, ctx: ResolveContext, *, rows: int = 3) -> list[Candidate]:
    """Crossref's reference matching: free text (or title + author + year) to works.

    Confidence is left at 0: callers score candidates against what they searched for.
    """
    async with ctx.limit("crossref-search", SEARCH_SLOTS):
        for delay in (*RETRY_DELAYS, None):
            try:
                return await _search(text, ctx, rows)
            except SourceError as exc:
                if "rate-limiting" not in exc.message or delay is None:
                    raise
                await asyncio.sleep(delay)
        return []


async def _search(text: str, ctx: ResolveContext, rows: int) -> list[Candidate]:
    data = await get_json(
        ctx,
        "Crossref",
        API.rstrip("/"),
        params={"query.bibliographic": text[:500], "rows": rows, "select": "DOI,type,title,subtitle,author,editor,"
                "container-title,publisher,volume,issue,page,ISSN,ISBN,published-print,published-online,issued"},
        headers={"User-Agent": user_agent(ctx)},
    )
    items = ((data or {}).get("message") or {}).get("items") or []
    return [
        Candidate(
            draft=to_draft(work),
            source_system="crossref",
            source_identifier=normalize_doi(work.get("DOI") or "") or "",
            match_method="search",
            confidence=0.0,
            raw=work,
        )
        for work in items
        if work.get("DOI")
    ]
