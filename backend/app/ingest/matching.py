"""Match imported entries to records: the library's first, then Crossref.

Each candidate gets a confidence from comparing it with the entry (title,
first author, year), so the review screen can preselect good matches and leave
doubtful ones to the list-builder. An AI matcher can later add candidates and
scores through the same shape.
"""
import asyncio
import re
import unicodedata
from difflib import SequenceMatcher

from app.ingest import pipeline
from app.ingest.candidate import Candidate, SourceError
from app.ingest.draft import CitationDraft
from app.ingest.parsers import Entry
from app.ingest.resolvers import ResolveContext, crossref, primo

MAX_CANDIDATES = 5
# Candidates scoring below this aren't worth showing
MIN_SCORE = 0.3
# Matches at or above this are preselected in review
GOOD_MATCH = 0.85

_STOPWORDS = {"the", "a", "an", "of", "and", "in", "on", "to", "for", "with", "by", "at", "from", "le", "la", "les", "de", "des", "du", "et"}


def normalize(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _main_title(title: str | None) -> str:
    return re.split(r"[:?!.]", title or "", maxsplit=1)[0]


def _surname(name: str) -> str:
    # "Carr, Edward Hallett" → carr; "Marc Bloch" → bloch
    name = name.split(",", 1)[0] if "," in name else (name.split() or [""])[-1]
    return normalize(name)


def _similar(a: str, b: str) -> float:
    """Characters (tolerates typos) and words (shared letters alone aren't a match), averaged."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    chars = SequenceMatcher(None, a, b).ratio()
    wa, wb = set(a.split()), set(b.split())
    words = 2 * len(wa & wb) / (len(wa) + len(wb))
    return (chars + words) / 2


def _title_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    # Compare whole titles and main titles: one side may lack the subtitle
    return max(_similar(a, b), _similar(_main_title(a), _main_title(b)))


def _title_in_text(title: str | None, text: str) -> float:
    """How well a candidate's title fits a pasted reference: the share of its main-title
    words found in the reference, scaled down when it's much shorter than the title the
    reference seems to have (a book called "History" is in every history reference)."""
    words = [w for w in normalize(_main_title(title) or title).split() if w not in _STOPWORDS]
    if not words:
        return 0.0
    present = set(normalize(text).split())
    contained = sum(w in present for w in words) / len(words)
    guessed = guess_title(text)
    guessed_words = [w for w in normalize(_main_title(guessed) or guessed).split() if w not in _STOPWORDS]
    if guessed_words and len(words) < len(guessed_words):
        contained *= len(words) / len(guessed_words)
    return contained


def guess_surname(text: str) -> str | None:
    """The first author's surname in a pasted reference ("Carr, E. H. …" → carr)."""
    match = re.match(r"\s*([^\W\d_][\w'’-]+(?:\s[^\W\d_][\w'’-]+)?),", text)
    return normalize(match.group(1)) if match else None


def _year_score(a: int | None, b: int | None) -> float:
    if not a or not b:
        return 0.5
    if a == b:
        return 1.0
    # Off by one is common (catalogue vs. copyright date); further apart, reprints and editions
    return 0.8 if abs(a - b) == 1 else 0.3


def score(entry: Entry, candidate: CitationDraft) -> float:
    """0–1: how likely `candidate` is the item `entry` describes."""
    if entry.structured and entry.draft.title:
        title = _title_similarity(entry.draft.title, candidate.title)
        theirs = {_surname(n) for n in candidate.author or []}
        mine = [_surname(n) for n in entry.draft.author or []]
        author = 0.5 if not mine or not theirs else (1.0 if mine[0] in theirs else 0.0)
        year = _year_score(entry.draft.year, candidate.year)
    else:
        title = _title_in_text(candidate.title, entry.text)
        surnames = [_surname(n) for n in candidate.author or []]
        author = 0.5 if not surnames else (1.0 if surnames[0] and surnames[0] in normalize(entry.text).split() else 0.0)
        year = _year_score(entry.draft.year, candidate.year)
    if title < 0.5:
        return round(title * 0.5, 2)  # a different title: not a match, whatever else agrees
    return round(0.6 * title + 0.25 * author + 0.15 * year, 2)


def guess_title(text: str) -> str | None:
    """The likely title in a pasted reference, for searching (scoring checks it anyway)."""
    text = re.sub(r"https?://\S+|\b10\.\d{4,9}/\S+|ISBN[\s:]*[\dXx-]+", " ", text)
    # APA: Author (Year). Title. …
    if match := re.search(r"\(\d{4}[a-z]?\)\.?\s+(.+?)[.?!](?:\s|$)", text):
        return match.group(1)
    # Chicago/MLA: Author. Title. Place: Publisher, Year. → the longest segment without a year
    segments = [s.strip() for s in re.split(r"(?<![A-Z])\.\s+", text) if s.strip()]
    segments = [s for s in segments[1:] if not re.search(r"\b\d{4}\b", s) and ":" not in s[:25]] or segments[1:]
    return max(segments, key=len, default=None)


def _primo_query(entry: Entry) -> str | None:
    title = entry.draft.title if entry.structured else guess_title(entry.text)
    words = normalize(_main_title(title) or title).split()[:10]
    if not words:
        return None
    query = f"title,contains,{' '.join(words)}"
    surname = _surname(entry.draft.author[0]) if entry.structured and entry.draft.author else guess_surname(entry.text)
    if surname:
        query += f",AND;creator,contains,{surname}"
    return query


def _crossref_query(entry: Entry) -> str:
    if not entry.structured:
        return entry.text
    d = entry.draft
    return " ".join(str(p) for p in (d.title, (d.author or [""])[0], d.year, d.metadata.get("journal_name")) if p)


def _source_rank(candidate: Candidate) -> int:
    if candidate.source_system == "alma":
        return 0
    if candidate.source_system == "primo":
        return 1 if candidate.source_identifier.startswith("alma") else 2
    return 3


async def match(entry: Entry, ctx: ResolveContext) -> tuple[list[Candidate], list[str]]:
    """Candidates for one entry, best first, and warnings from sources that failed."""
    warnings: list[str] = []
    idents = " ".join(v for v in (entry.draft.doi, entry.draft.isbn) if v)
    if idents:
        found = await pipeline.lookup(idents, ctx)
        warnings += found.warnings
        if found.candidates:
            return found.candidates[:MAX_CANDIDATES], warnings

    candidates: list[Candidate] = []
    if primo.available(ctx) and (query := _primo_query(entry)):
        try:
            page = await primo.search_page(ctx, query, limit=5)
            local = [c for d in page.docs if (c := primo.to_candidate(d))]
            candidates += await pipeline.reconcile_holdings(local, ctx)
        except SourceError as exc:
            warnings.append(str(exc))
    if entry.draft.resource_type not in ("book", "ebook") or not candidates:
        try:
            candidates += await crossref.search_bibliographic(_crossref_query(entry), ctx)
        except SourceError as exc:
            warnings.append(str(exc))

    seen: set[tuple[str, str]] = set()
    unique = []
    for candidate in candidates:
        key = (candidate.source_system, candidate.source_identifier)
        if key in seen or not candidate.source_identifier:
            continue
        seen.add(key)
        candidate.match_method = "search"
        candidate.confidence = score(entry, candidate.draft)
        if candidate.confidence >= MIN_SCORE:
            unique.append(candidate)
    # On equal scores prefer the library's own record (bound, synced, best link), then
    # other catalogue records, then the discovery index, then Crossref
    unique.sort(key=lambda c: (-c.confidence, _source_rank(c)))
    return unique[:MAX_CANDIDATES], warnings


async def match_all(entries: list[Entry], ctx: ResolveContext, *, concurrency: int = 4):
    """Match entries a few at a time; yields (index, candidates, warnings) as each finishes."""
    limit = asyncio.Semaphore(concurrency)

    async def one(i: int, entry: Entry):
        async with limit:
            return i, *(await match(entry, ctx))

    for task in asyncio.as_completed([one(i, e) for i, e in enumerate(entries)]):
        yield await task
