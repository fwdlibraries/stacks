"""Parse bulk imports into entries: RIS, BibTeX, or a pasted bibliography.

Each entry is a CitationDraft (what the file says) plus the original text, which
matching uses when there's little structure, e.g. a pasted reference.
"""
import re
from dataclasses import dataclass, field
from typing import Literal

from app.ingest.draft import CitationDraft
from app.ingest.identifiers import detect, normalize_doi, normalize_isbn

Format = Literal["ris", "bibtex", "text"]
MAX_ENTRIES = 300


@dataclass
class Entry:
    draft: CitationDraft
    text: str  # the entry as written, for display and free-text matching
    raw: dict = field(default_factory=dict)
    structured: bool = True  # False for pasted references: fields are guesses


class ParseError(ValueError):
    pass


def detect_format(text: str) -> Format:
    if re.search(r"^TY  - ", text, re.MULTILINE):
        return "ris"
    if re.search(r"^\s*@\w+\s*[{(]", text, re.MULTILINE):
        return "bibtex"
    return "text"


def parse(text: str, fmt: Format | Literal["auto"] = "auto") -> list[Entry]:
    fmt = detect_format(text) if fmt == "auto" else fmt
    entries = {"ris": parse_ris, "bibtex": parse_bibtex, "text": parse_text}[fmt](text)
    if len(entries) > MAX_ENTRIES:
        raise ParseError(f"That's {len(entries)} entries; import at most {MAX_ENTRIES} at a time.")
    return entries


_YEAR = r"(1[5-9]\d\d|20\d\d)"


def _year(value: str | None) -> int | None:
    """A publication year: a 4-digit year, ignoring date ranges in titles ("1789-1848")."""
    value = value or ""
    if match := re.search(rf"\({_YEAR}[a-z]?\)", value):  # APA: (1961)
        return int(match.group(1))
    value = re.sub(rf"\b{_YEAR}\s*[-–]\s*{_YEAR}\b", " ", value)
    years = re.findall(rf"\b{_YEAR}\b", value)
    return int(years[-1]) if years else None


def _pages(start: str | None, end: str | None) -> str | None:
    if start and end:
        return f"{start}-{end}"
    return start or None


# ── RIS ──────────────────────────────────────────────────────────────────────

RIS_TYPES = {
    "JOUR": "journal_article", "JFULL": "journal_article", "MGZN": "journal_article", "NEWS": "journal_article",
    "EJOUR": "journal_article", "BOOK": "book", "EBOOK": "ebook", "EDBOOK": "book", "CHAP": "book_chapter",
    "ECHAP": "book_chapter", "ELEC": "website", "WEB": "website", "VIDEO": "av_media", "MPCT": "av_media",
    "SOUND": "av_media",
}
_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])  -(?: (.*))?$")


def parse_ris(text: str) -> list[Entry]:
    entries: list[Entry] = []
    record: dict[str, list[str]] = {}
    lines: list[str] = []
    for line in text.splitlines():
        match = _RIS_LINE.match(line.rstrip())
        if not match:
            if record and line.strip() and lines:  # continuation of the previous value
                last = next(reversed(record))
                record[last][-1] += " " + line.strip()
            continue
        tag, value = match.group(1), (match.group(2) or "").strip()
        if tag == "TY":
            record, lines = {"TY": [value]}, [line]
        elif tag == "ER":
            if record:
                entries.append(_ris_entry(record, "\n".join(lines)))
            record, lines = {}, []
        elif record:
            record.setdefault(tag, []).append(value)
            lines.append(line)
    if record:  # missing final ER
        entries.append(_ris_entry(record, "\n".join(lines)))
    return entries


def _ris_entry(r: dict[str, list[str]], text: str) -> Entry:
    def first(*tags: str) -> str | None:
        return next((r[t][0] for t in tags if r.get(t) and r[t][0]), None)

    rtype = RIS_TYPES.get(first("TY") or "", "other")
    title = first("TI", "T1", "CT")
    container = first("T2", "JO", "JF", "JA", "BT")
    if rtype == "book" and title is None and container:  # some tools put book titles in BT
        title, container = container, None
    metadata = {}
    if container:
        metadata["journal_name" if rtype == "journal_article" else "container_title"] = container
    isbns = [i for v in r.get("SN", []) if (i := normalize_isbn(v))]
    issn = next((v for v in r.get("SN", []) if re.fullmatch(r"\d{4}-?\d{3}[\dXx]", v.strip())), None)
    return Entry(
        draft=CitationDraft(
            title=title,
            resource_type=rtype,
            author=[a for a in r.get("AU", []) + r.get("A1", []) if a],
            editor=[a for a in r.get("ED", []) + r.get("A2", []) if a] if rtype != "journal_article" else [],
            year=_year(first("PY", "Y1", "DA")),
            publisher=first("PB"),
            place_of_publication=first("CY"),
            edition=first("ET"),
            volume=first("VL"),
            issue=first("IS"),
            pages=_pages(first("SP"), first("EP")),
            isbn=isbns[0] if isbns else None,
            issn=issn,
            doi=normalize_doi(first("DO") or ""),
            url=first("UR", "L2"),
            metadata=metadata,
        ),
        text=text,
        raw=r,
    )


# ── BibTeX ───────────────────────────────────────────────────────────────────

BIBTEX_TYPES = {
    "article": "journal_article", "book": "book", "inbook": "book_chapter", "incollection": "book_chapter",
    "online": "website", "misc": "other", "video": "av_media", "phdthesis": "other", "mastersthesis": "other",
}
_LATEX_ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "c": "\u0327", "=": "\u0304"}


def _delatex(value: str) -> str:
    import unicodedata

    # {\'e} / \'{e} / \'e → é
    value = re.sub(
        r"\{?\\([`'^\"~=c])\{?([A-Za-z])\}?\}?",
        lambda m: unicodedata.normalize("NFC", m.group(2) + _LATEX_ACCENTS[m.group(1)]),
        value,
    )
    value = value.replace("\\&", "&").replace("--", "–").replace("~", " ")
    value = re.sub(r"\\[A-Za-z]+\s*", "", value)  # other commands (\emph etc.)
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


def _bibtex_value(body: str, i: int) -> tuple[str, int]:
    """Read one field value starting at body[i]: {…}, "…", a number, or a macro, joined by #."""
    parts = []
    while True:
        while i < len(body) and body[i].isspace():
            i += 1
        if i < len(body) and body[i] == "{":
            depth, start = 0, i
            while i < len(body):
                depth += {"{": 1, "}": -1}.get(body[i], 0)
                i += 1
                if depth == 0:
                    break
            parts.append(body[start + 1 : i - 1])
        elif i < len(body) and body[i] == '"':
            start, i, depth = i + 1, i + 1, 0
            while i < len(body) and not (body[i] == '"' and depth == 0):
                depth += {"{": 1, "}": -1}.get(body[i], 0)
                i += 1
            parts.append(body[start:i])
            i += 1
        else:
            match = re.match(r"[^,#}\s]+", body[i:])
            parts.append(match.group(0) if match else "")
            i += len(match.group(0)) if match else 0
        while i < len(body) and body[i].isspace():
            i += 1
        if i < len(body) and body[i] == "#":
            i += 1
            continue
        return "".join(parts), i


def _bibtex_entries(text: str):
    for match in re.finditer(r"@(\w+)\s*[{(]", text):
        kind = match.group(1).lower()
        if kind in ("comment", "preamble", "string"):
            continue
        start, depth, i = match.end(), 1, match.end()
        while i < len(text) and depth:
            depth += {"{": 1, "(": 1, "}": -1, ")": -1}.get(text[i], 0)
            i += 1
        yield kind, text[start : i - 1], text[match.start() : i]


def parse_bibtex(text: str) -> list[Entry]:
    entries = []
    for kind, body, original in _bibtex_entries(text):
        key_end = body.find(",")
        fields: dict[str, str] = {}
        i = key_end + 1 if key_end >= 0 else len(body)
        while i < len(body):
            match = re.compile(r"\s*([\w-]+)\s*=\s*").match(body, i)
            if not match:
                i += 1
                continue
            value, i = _bibtex_value(body, match.end())
            fields[match.group(1).lower()] = _delatex(value)
            while i < len(body) and body[i] in ", \n\r\t":
                i += 1
        entries.append(_bibtex_entry(kind, fields, original))
    return entries


def _names(value: str | None) -> list[str]:
    return [n.strip() for n in re.split(r"\s+and\s+", value or "") if n.strip()]


def _bibtex_entry(kind: str, f: dict[str, str], original: str) -> Entry:
    rtype = BIBTEX_TYPES.get(kind, "other")
    container = f.get("journal") or f.get("journaltitle") or f.get("booktitle")
    metadata = {}
    if container:
        metadata["journal_name" if rtype == "journal_article" else "container_title"] = container
    isbn = normalize_isbn(f.get("isbn", ""))
    return Entry(
        draft=CitationDraft(
            title=f.get("title"),
            resource_type=rtype,
            author=_names(f.get("author")),
            editor=_names(f.get("editor")),
            year=_year(f.get("year") or f.get("date")),
            publisher=f.get("publisher"),
            place_of_publication=f.get("address") or f.get("location"),
            edition=f.get("edition"),
            volume=f.get("volume"),
            issue=f.get("number") or f.get("issue"),
            pages=(f.get("pages") or "").replace("–", "-") or None,
            isbn=isbn,
            issn=f.get("issn"),
            doi=normalize_doi(f.get("doi", "")),
            url=f.get("url"),
            metadata=metadata,
        ),
        text=original.strip(),
        raw={"type": kind, **f},
    )


# ── Pasted text ──────────────────────────────────────────────────────────────

_NUMBERING = re.compile(r"^\s*(?:\[\d+\]|\d+[.)]|[-*•])\s+")


def _chunks(text: str) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    numbered = [bool(_NUMBERING.match(line)) for line in lines]
    if lines and sum(numbered) >= max(2, len(lines) // 2):
        # Numbered list: each number starts a reference; other lines continue it
        chunks: list[str] = []
        for line, starts in zip(lines, numbered, strict=True):
            if starts or not chunks:
                chunks.append(line)
            else:
                chunks[-1] += " " + line
        return chunks
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    # Blank-line separated references that wrap over several lines
    if len(blocks) > 1 and len(blocks) < len(lines):
        return blocks
    return lines


def parse_text(text: str) -> list[Entry]:
    """References one per line, per paragraph, or per number in a numbered list."""
    entries = []
    for chunk in _chunks(text):
        reference = _NUMBERING.sub("", " ".join(chunk.split()))
        if len(reference) < 10:
            continue
        idents = detect(reference)
        entries.append(
            Entry(
                draft=CitationDraft(
                    year=_year(reference),
                    doi=next((i.value for i in idents if i.kind == "doi"), None),
                    isbn=next((i.value for i in idents if i.kind == "isbn"), None),
                ),
                text=reference,
                structured=False,
            )
        )
    return entries
