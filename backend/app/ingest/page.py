"""A web page's metadata → an entry to match (browser extension).

The extension collects <meta> tags and JSON-LD from the page; this maps the
common vocabularies onto a CitationDraft:

- Highwire Press citation_* tags (Google Scholar's; most publishers and repositories)
- Dublin Core (dc.* / DC.* / dcterms.*), PRISM (prism.*), Open Graph (og:*)
- schema.org JSON-LD (ScholarlyArticle, Article, Book, Chapter, WebPage, ...)
- a DOI in the URL (doi.org/…, …/doi/10.…)
"""
import re
from urllib.parse import unquote, urlsplit

from app.ingest.draft import CitationDraft
from app.ingest.identifiers import normalize_doi, normalize_isbn
from app.ingest.parsers import Entry, _year

JSONLD_TYPES = {
    "scholarlyarticle": "journal_article",
    "article": "journal_article",
    "newsarticle": "journal_article",
    "book": "book",
    "chapter": "book_chapter",
    "videoobject": "av_media",
    "movie": "av_media",
    "audioobject": "av_media",
    "podcastepisode": "av_media",
}


def _get(meta: dict[str, list[str]], *names: str) -> str | None:
    lower = {k.lower(): v for k, v in meta.items()}
    for name in names:
        for value in lower.get(name.lower(), []):
            if value and value.strip():
                return value.strip()
    return None


def _all(meta: dict[str, list[str]], *names: str) -> list[str]:
    lower = {k.lower(): v for k, v in meta.items()}
    return [v.strip() for name in names for v in lower.get(name.lower(), []) if v and v.strip()]


def _jsonld_items(blocks: list) -> list[dict]:
    items: list[dict] = []
    for block in blocks:
        for item in block if isinstance(block, list) else [block]:
            if isinstance(item, dict):
                items.extend(item["@graph"] if isinstance(item.get("@graph"), list) else [item])
    return [i for i in items if isinstance(i, dict)]


def _jsonld_type(item: dict) -> str:
    kinds = item.get("@type") or []
    kinds = kinds if isinstance(kinds, list) else [kinds]
    return next((JSONLD_TYPES[k.lower()] for k in kinds if isinstance(k, str) and k.lower() in JSONLD_TYPES), "")


def _jsonld_names(value) -> list[str]:
    people = value if isinstance(value, list) else [value] if value else []
    names = []
    for person in people:
        if isinstance(person, str):
            names.append(person)
        elif isinstance(person, dict):
            if person.get("familyName"):
                names.append(f"{person['familyName']}, {person.get('givenName', '')}".strip(", "))
            elif person.get("name"):
                names.append(person["name"])
    return names


def doi_in_url(url: str) -> str | None:
    path = unquote(urlsplit(url).path)
    match = re.search(r"(10\.\d{4,9}/\S+)", path)
    if not match:
        return None
    # Publisher paths often continue after the DOI (/full, /pdf, /abstract)
    doi = re.sub(r"/(full|pdf|epdf|abstract|summary|html|references|figures)(/.*)?$", "", match.group(1))
    return normalize_doi(doi)


def to_entry(url: str, title: str | None, meta: dict[str, list[str]], jsonld: list) -> Entry:
    items = _jsonld_items(jsonld)
    work = next((i for i in items if _jsonld_type(i)), None) or {}
    part_of = work.get("isPartOf") if isinstance(work.get("isPartOf"), dict) else {}

    journal = _get(meta, "citation_journal_title", "prism.publicationName", "dc.source") or part_of.get("name")
    book_title = _get(meta, "citation_book_title", "citation_inbook_title")
    isbn = next(
        (i for v in _all(meta, "citation_isbn", "prism.isbn", "dc.identifier") + [str(work.get("isbn") or "")]
         if (i := normalize_isbn(v))),
        None,
    )
    doi = next(
        (d for v in _all(meta, "citation_doi", "prism.doi", "dc.identifier", "dc.identifier.doi", "bepress_citation_doi")
         + [str(work.get("doi") or ""), str(work.get("identifier") or "")]
         if (d := normalize_doi(v))),
        None,
    ) or doi_in_url(url)

    if journal or _get(meta, "citation_journal_title"):
        rtype = "journal_article"
    elif book_title:
        rtype = "book_chapter"
    elif _jsonld_type(work):
        rtype = _jsonld_type(work)
    elif isbn:
        rtype = "book"
    else:
        rtype = "website"

    authors = (
        _all(meta, "citation_author", "dc.creator", "dcterms.creator", "dc.contributor.author")
        or _jsonld_names(work.get("author"))
        or _all(meta, "author")
    )
    first_page, last_page = _get(meta, "citation_firstpage", "prism.startingPage"), _get(meta, "citation_lastpage", "prism.endingPage")
    work_title = (
        _get(meta, "citation_title", "dc.title", "dcterms.title", "prism.title")
        or work.get("headline") or work.get("name")
        or _get(meta, "og:title")
        or title
    )
    metadata = {}
    if journal:
        metadata["journal_name"] = journal
    elif book_title:
        metadata["container_title"] = book_title
    site = _get(meta, "og:site_name")
    if rtype == "website" and site:
        metadata["site_name"] = site

    draft = CitationDraft(
        title=(work_title or "").strip() or None,
        resource_type=rtype,
        author=authors,
        year=_year(
            _get(meta, "citation_publication_date", "citation_date", "citation_online_date", "dc.date",
                 "dcterms.issued", "prism.publicationDate", "article:published_time")
            or str(work.get("datePublished") or "")
        ),
        publisher=_get(meta, "citation_publisher", "dc.publisher", "dcterms.publisher")
        or ((work.get("publisher") or {}).get("name") if isinstance(work.get("publisher"), dict) else None),
        volume=_get(meta, "citation_volume", "prism.volume"),
        issue=_get(meta, "citation_issue", "prism.number"),
        pages=f"{first_page}-{last_page}" if first_page and last_page else first_page,
        isbn=isbn,
        issn=_get(meta, "citation_issn", "prism.issn", "prism.eIssn"),
        doi=doi,
        url=url if urlsplit(url).scheme in ("http", "https") else None,
        metadata=metadata,
    )
    return Entry(draft=draft, text=draft.title or url, raw={"url": url}, structured=bool(draft.title))
