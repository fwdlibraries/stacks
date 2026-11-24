"""Student-facing links, built when a list is shown rather than stored.

Stored links go stale when subscriptions, platforms or the discovery interface
change. Instead each citation keeps identifiers and metadata, and its link is
derived on every request from the organization's current discovery settings:

- library records (Alma, or local records read from Primo): the full record in
  the discovery system, which shows current availability and access
- articles and chapters: an OpenURL to the library's link resolver, which works
  out today's full-text options when the student clicks
- otherwise: the DOI, then the citation's own URL

Primo's /discovery/... routes are used deliberately: NDE redirects them to its
own /nde/... routes, so the same links work for VE and NDE views.
"""
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.sources import PrimoConfig
from app.models.models import Citation, LibrarySource, ReadingList

LinkKind = Literal["library_record", "full_text", "doi", "web"]

# Identifies Stacks to the resolver (shows up in Alma usage reports)
REFERRER_ID = "info:sid/stacks"


@dataclass(frozen=True)
class LinkSettings:
    discovery_url: str
    vid: str
    institution: str

    @classmethod
    def from_primo(cls, config: PrimoConfig) -> "LinkSettings":
        return cls(discovery_url=config.discovery_url, vid=config.vid, institution=config.institution)


@dataclass(frozen=True)
class Link:
    url: str
    kind: LinkKind


async def load_link_settings(db: AsyncSession, organization_id: uuid.UUID) -> LinkSettings | None:
    """The org's discovery settings for links. Needs no API key: links are public URLs."""
    row = await db.scalar(
        select(LibrarySource).where(
            LibrarySource.organization_id == organization_id,
            LibrarySource.kind == "primo",
            LibrarySource.is_active.is_(True),
        )
    )
    if row is None:
        return None
    try:
        return LinkSettings.from_primo(PrimoConfig.model_validate(row.config))
    except ValueError:
        return None


def library_record_id(citation: Citation) -> str | None:
    """The Primo record ID for a citation that is a local library record."""
    if citation.source_status == "unlinked" or not citation.source_identifier:
        return None
    if citation.source_system == "alma" and citation.source_identifier.isdigit():
        return f"alma{citation.source_identifier}"
    if citation.source_system == "primo" and re.fullmatch(r"alma\d+", citation.source_identifier):
        return citation.source_identifier
    return None


def full_record_url(settings: LinkSettings, record_id: str) -> str:
    query = urlencode({"docid": record_id, "context": "L", "vid": settings.vid, "lang": "en"})
    return f"{settings.discovery_url}/discovery/fulldisplay?{query}"


def _first_author(citation: Citation) -> dict[str, str]:
    if not citation.author:
        return {}
    family, _, given = citation.author[0].partition(",")
    params = {"rft.au": citation.author[0], "rft.aulast": family.strip()}
    if given.strip():
        params["rft.aufirst"] = given.strip()
    return params


def openurl_params(citation: Citation) -> dict[str, str]:
    """OpenURL 1.0 (KEV) context object describing the citation."""
    meta = citation.metadata_ or {}
    params: dict[str, str] = {"url_ver": "Z39.88-2004", "ctx_ver": "Z39.88-2004", "rfr_id": REFERRER_ID}
    rtype = citation.resource_type.value if citation.resource_type else "other"

    if rtype == "journal_article":
        # Manually entered articles keep the journal in `publisher` (the form labels it "Journal")
        journal = meta.get("journal_name") or citation.publisher
        params |= {"rft_val_fmt": "info:ofi/fmt:kev:mtx:journal", "rft.genre": "article", "rft.atitle": citation.title}
        if journal:
            params["rft.jtitle"] = journal
    elif rtype == "book_chapter":
        params |= {"rft_val_fmt": "info:ofi/fmt:kev:mtx:book", "rft.genre": "bookitem", "rft.atitle": citation.title}
        if book := meta.get("container_title") or meta.get("book_title"):
            params["rft.btitle"] = book
    else:
        params |= {"rft_val_fmt": "info:ofi/fmt:kev:mtx:book", "rft.genre": "book", "rft.btitle": citation.title}
        if citation.publisher:
            params["rft.pub"] = citation.publisher

    params |= _first_author(citation)
    for key, value in {
        "rft.date": str(citation.year) if citation.year else None,
        "rft.volume": citation.volume,
        "rft.issue": citation.issue,
        "rft.pages": citation.pages,
        "rft.issn": citation.issn,
        "rft.isbn": citation.isbn,
    }.items():
        if value:
            params[key] = value
    if citation.pages and (match := re.fullmatch(r"\s*(\w+)\s*[-–]\s*(\w+)\s*", citation.pages)):
        params["rft.spage"], params["rft.epage"] = match.groups()
    if citation.doi:
        params["rft_id"] = f"info:doi/{citation.doi}"
    return params


def openurl(settings: LinkSettings, citation: Citation) -> str:
    query = {"institution": settings.institution, "vid": settings.vid, **openurl_params(citation)}
    return f"{settings.discovery_url}/discovery/openurl?{urlencode(query)}"


def _resolvable(citation: Citation) -> bool:
    """Enough for the link resolver to find the item."""
    rtype = citation.resource_type.value if citation.resource_type else "other"
    if rtype in ("journal_article", "book_chapter"):
        return bool(citation.doi or citation.issn or (citation.metadata_ or {}).get("journal_name") or citation.publisher)
    if rtype in ("book", "ebook"):
        return bool(citation.isbn or citation.doi)
    return False


def citation_link(citation: Citation, settings: LinkSettings | None) -> Link | None:
    rtype = citation.resource_type.value if citation.resource_type else "other"
    if settings is not None:
        if record_id := library_record_id(citation):
            return Link(full_record_url(settings, record_id), "library_record")
        if rtype != "website" and _resolvable(citation):
            return Link(openurl(settings, citation), "full_text")
    if citation.url and rtype == "website":
        return Link(citation.url, "web")
    if citation.doi:
        return Link(f"https://doi.org/{citation.doi}", "doi")
    if citation.url:
        return Link(citation.url, "web")
    return None


def annotate(reading_list: ReadingList, settings: LinkSettings | None) -> ReadingList:
    """Set `link_url`/`link_kind` on every citation for the response schemas."""
    for section in reading_list.sections:
        annotate_citations(section.citations, settings)
    return reading_list


def go_url(citation: Citation) -> str:
    """Stacks' click-through address; resolves at click time (app/routers/go.py)."""
    return f"/api/v1/go/{citation.id}"


def may_resolve(citation: Citation, settings: LinkSettings | None) -> bool:
    """Whether a resolver could find something even without a render-time link.

    A DOI is worth trying anywhere (LibKey, open access); the library's resolver
    needs a discovery system configured.
    """
    if citation.doi:
        return True
    return settings is not None and bool(citation.isbn or citation.issn or library_record_id(citation))


def annotate_citations(citations: Iterable[Citation], settings: LinkSettings | None) -> None:
    """Point each citation at /go when it has (or may resolve to) a link.

    `link_kind` is the render-time link's kind: a hint for the label. The click
    itself may go somewhere more direct (LibKey, a full-text platform).
    """
    for citation in citations:
        link = citation_link(citation, settings)
        has_link = link is not None or may_resolve(citation, settings)
        citation.link_url = go_url(citation) if has_link else None  # type: ignore[attr-defined]
        citation.link_kind = (link.kind if link else "full_text") if has_link else None  # type: ignore[attr-defined]
