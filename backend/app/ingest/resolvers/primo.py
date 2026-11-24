"""Primo VE / NDE search API (the same API serves both interfaces).

Local results are the library's Alma records: they become `alma` candidates, and
adding one fetches the authoritative record from Alma. Central Discovery Index
(CDI) results, mostly articles, become `primo` candidates built from their PNX.
"""
import re
from dataclasses import dataclass

from app.ingest import marc
from app.ingest.candidate import Candidate
from app.ingest.draft import CitationDraft
from app.ingest.identifiers import normalize_doi, normalize_isbn
from app.ingest.resolvers.base import ResolveContext, Resolver, get_json
from app.ingest.sources import PrimoConfig

# PNX display type → Stacks resource type
TYPES = {
    "article": "journal_article",
    "review": "journal_article",
    "newspaper_article": "journal_article",
    "book": "book",
    "book_chapter": "book_chapter",
    "video": "av_media",
    "audio": "av_media",
    "audio_video": "av_media",
    "web_resource": "website",
    "website": "website",
}

# delivery.availability → what students can expect
AVAILABILITY = {
    "not_restricted": "online",
    "fulltext": "online",
    "fulltext_linktorsrc": "online",
    "fulltext_multiple": "online",
    "available_in_library": "in_library",
    "available_in_maininstitution": "in_library",
    "available_in_institution": "in_library",
    "check_holdings": "check_holdings",
    "no_fulltext": "citation_only",
}

MAX_LIMIT = 25


def available(ctx: ResolveContext) -> bool:
    return "primo" in ctx.sources


def _query_value(text: str) -> str:
    # Primo's q is "field,precision,value" with ';' joining clauses: keep the value plain
    return re.sub(r"[;\s]+", " ", text).strip()


@dataclass
class SearchPage:
    total: int
    docs: list[dict]


async def search_page(ctx: ResolveContext, query: str, *, offset: int = 0, limit: int = 10) -> SearchPage:
    """One page of Primo results. `query` uses Primo syntax, e.g. "isbn,exact,978…"."""
    source = ctx.sources["primo"]
    config: PrimoConfig = source.config  # type: ignore[assignment]
    params = {
        "vid": config.vid,
        "tab": config.tab,
        "scope": config.scope,
        "q": query,
        "limit": min(limit, MAX_LIMIT),
        "offset": offset,
    }
    data = await get_json(
        ctx,
        "Primo",
        f"{config.api_base}/primo/v1/search",
        params=params,
        headers={"Authorization": f"apikey {source.api_key}", "Accept": "application/json"},
    )
    data = data or {}
    return SearchPage(total=int((data.get("info") or {}).get("total") or 0), docs=data.get("docs") or [])


async def search(ctx: ResolveContext, query: str, *, limit: int = 10, local_only: bool = False) -> list[dict]:
    """Primo search; returns PNX documents."""
    docs = (await search_page(ctx, query, limit=limit)).docs
    return [d for d in docs if d.get("context") == "L"] if local_only else docs


def mms_id(doc: dict) -> str | None:
    """The Alma MMS ID behind a local Primo record; None for CDI and other non-Alma records.

    CDI records also carry numeric `sourcerecordid`s (e.g. a ProQuest ID), so the
    record must be an Alma one: recordid "alma<MMS ID>".
    """
    control = (doc.get("pnx") or {}).get("control") or {}
    for value in control.get("recordid") or []:
        if value.startswith("alma") and value[4:].isdigit():
            return value[4:]
    return None


def record_id(doc: dict) -> str | None:
    return next(iter(((doc.get("pnx") or {}).get("control") or {}).get("recordid") or []), None)


def _first(section: dict, key: str) -> str | None:
    values = section.get(key) or []
    return values[0] if values else None


def _strip_subfields(value: str) -> str:
    # PNX display values can carry "$$Q<search value>" and similar suffixes
    return value.split("$$", 1)[0]


def _names(display: dict) -> list[str]:
    names: list[str] = []
    for value in display.get("creator") or []:
        for part in _strip_subfields(value).split(";"):
            if (name := marc.clean(part)) and name not in names:
                names.append(name)
    return names


def to_draft(doc: dict) -> CitationDraft:
    pnx = doc.get("pnx") or {}
    display, addata = pnx.get("display") or {}, pnx.get("addata") or {}
    rtype = TYPES.get(_first(display, "type") or "", "other")
    date = _first(addata, "date") or _first(display, "creationdate") or ""
    year = re.search(r"\d{4}", date)
    spage, epage = _first(addata, "spage"), _first(addata, "epage")
    pages = f"{spage}-{epage}" if spage and epage else spage
    isbns = [i for raw in addata.get("isbn") or [] if (i := normalize_isbn(raw))]
    journal = _first(addata, "jtitle")
    title = _first(display, "title")
    return CitationDraft(
        # Catalogue titles keep ISBD spacing ("Title : subtitle")
        title=marc.clean(_strip_subfields(title).replace(" : ", ": ")) if title else None,
        resource_type=rtype,
        author=_names(display),
        year=int(year.group()) if year else None,
        publisher=_first(addata, "pub") or marc.clean(_strip_subfields(_first(display, "publisher") or "")),
        place_of_publication=_first(addata, "cop"),
        edition=marc.clean(_first(display, "edition")),
        volume=_first(addata, "volume"),
        issue=_first(addata, "issue"),
        pages=pages,
        isbn=isbns[0] if isbns else None,
        issn=_first(addata, "issn"),
        doi=normalize_doi(_first(addata, "doi") or ""),
        metadata={"journal_name": journal} if journal else {},
    )


def availability(doc: dict) -> str | None:
    return AVAILABILITY.get(_first(doc.get("delivery") or {}, "availability") or "")


def to_candidate(doc: dict, *, from_primo: bool = False) -> Candidate | None:
    """A search result as a candidate: local records point at Alma, CDI at Primo.

    `from_primo` keeps a local record as Primo's copy (for records the institution's
    Alma can't serve, such as consortium Network Zone records).
    """
    draft = to_draft(doc)
    if (mms := mms_id(doc)) and not from_primo:
        system, identifier = "alma", mms
    elif rid := record_id(doc):
        system, identifier = "primo", rid
    else:
        return None
    return Candidate(
        draft=draft,
        source_system=system,
        source_identifier=identifier,
        match_method="search",
        # The list-builder picks the exact record, so the match itself is certain
        confidence=1.0,
        raw={"pnx": doc.get("pnx"), "context": doc.get("context")},
        availability=availability(doc),
    )


# Primo record IDs Stacks binds to: CDI records, and Alma records it reads from Primo
RECORD_ID = re.compile(r"cdi_[A-Za-z0-9_.-]+|alma\d{8,20}")


class PrimoResolver(Resolver):
    """Re-fetches records by Primo record ID: CDI records, and local records that the
    institution's Alma can't serve (consortium Network Zone records)."""

    system = "primo"

    def available(self, ctx: ResolveContext) -> bool:
        return available(ctx)

    async def fetch(self, source_identifier: str, ctx: ResolveContext) -> Candidate | None:
        if not self.available(ctx) or not RECORD_ID.fullmatch(source_identifier):
            return None
        # Local records are found by MMS ID, CDI records by their record ID
        term = source_identifier.removeprefix("alma")
        page = await search_page(ctx, f"any,exact,{term}", limit=5)
        doc = next((d for d in page.docs if record_id(d) == source_identifier), None)
        if doc is None:
            return None
        candidate = to_candidate(doc, from_primo=True)
        if candidate:
            candidate.match_method = "identifier"
        return candidate


async def search_candidates(
    ctx: ResolveContext, text: str, *, offset: int = 0, limit: int = 10
) -> tuple[int, list[Candidate]]:
    """Keyword search of the library's discovery scope, as candidates."""
    page = await search_page(ctx, f"any,contains,{_query_value(text)}", offset=offset, limit=limit)
    return page.total, [c for d in page.docs if (c := to_candidate(d))]
