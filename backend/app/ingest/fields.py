"""Candidate → Citation columns, shared by adding citations and the catalogue sync."""
from urllib.parse import urlsplit

from app.ingest.candidate import Candidate
from app.models.models import ResourceType

# Bibliographic columns a source controls (instructor fields are never touched)
SOURCE_FIELDS = (
    "resource_type", "title", "author", "editor", "year", "publisher", "place_of_publication",
    "edition", "volume", "issue", "pages", "isbn", "issn", "doi", "url", "metadata_",
)


class UnusableRecord(ValueError):
    """The record can't become a citation (e.g. it has no title)."""


def citation_fields(candidate: Candidate) -> dict:
    """Bibliographic Citation columns from a candidate, made safe to store and show."""
    draft = candidate.draft
    if not draft.title:
        raise UnusableRecord("That record has no title, so it can't be added")
    url = draft.url if draft.url and urlsplit(draft.url).scheme.lower() in ("http", "https") else None
    rtype = draft.resource_type if draft.resource_type in ResourceType.__members__ else "other"
    year = draft.year if draft.year and 1000 <= draft.year <= 2100 else None
    return {
        "resource_type": ResourceType(rtype),
        "title": draft.title,
        "author": draft.author or None,
        "editor": draft.editor or None,
        "year": year,
        "publisher": draft.publisher,
        "place_of_publication": draft.place_of_publication,
        "edition": draft.edition,
        "volume": draft.volume,
        "issue": draft.issue,
        "pages": draft.pages,
        "isbn": draft.isbn,
        "issn": draft.issn,
        "doi": draft.doi,
        "url": url,
        "metadata_": draft.metadata or {},
    }
