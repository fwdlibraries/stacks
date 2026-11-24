"""Recognize identifiers in whatever a list-builder pastes: a bare DOI or ISBN, a
doi.org link, an Alma MMS ID, or a line of text containing one of these."""
import re
from dataclasses import dataclass
from typing import Literal

IdentifierKind = Literal["doi", "isbn", "mms_id"]


@dataclass(frozen=True)
class Identifier:
    kind: IdentifierKind
    value: str  # normalized: DOI lowercased "10.…", ISBN-13 digits, MMS ID digits


# DOI: "10." + registrant + "/" + suffix (Crossref's recommended pattern, slightly relaxed).
# Trailing punctuation is trimmed afterwards since DOIs are often pasted from prose.
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
# Alma MMS IDs: start with 99, end with the 4-digit institution code; in practice
# 12–19 digits (shorter runs would be confused with ISBN-10s)
_MMS_ID = re.compile(r"\b(99\d{10,17})\b")
# ISBN candidates: 10 or 13 digits/X with optional hyphens or spaces between groups
_ISBN = re.compile(r"\b((?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx])\b")


def normalize_doi(value: str) -> str | None:
    match = _DOI.search(value)
    if not match:
        return None
    doi = match.group(1).rstrip(".,;:)]}'")
    return doi.lower()


def _isbn10_ok(digits: str) -> bool:
    total = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(digits))
    return total % 11 == 0


def _isbn13_ok(digits: str) -> bool:
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits))
    return total % 10 == 0


def isbn10_to_13(digits: str) -> str:
    core = "978" + digits[:9]
    check = (10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core)) % 10) % 10
    return core + str(check)


def normalize_isbn(value: str) -> str | None:
    """A valid ISBN as 13 digits, or None. Checksums are verified."""
    digits = re.sub(r"[-\s]", "", value)
    if len(digits) == 13 and digits.isdigit() and digits[:3] in ("978", "979") and _isbn13_ok(digits):
        return digits
    if len(digits) == 10 and digits[:9].isdigit() and (digits[9].isdigit() or digits[9] in "Xx"):
        return isbn10_to_13(digits) if _isbn10_ok(digits) else None
    return None


def detect(text: str) -> list[Identifier]:
    """Every identifier found in `text`, de-duplicated, in a stable order (DOI, MMS ID, ISBN)."""
    text = text.strip()
    found: list[Identifier] = []

    def add(ident: Identifier) -> None:
        if ident not in found:
            found.append(ident)

    for match in _DOI.finditer(text):
        if doi := normalize_doi(match.group(0)):
            add(Identifier("doi", doi))

    # Ignore digits inside DOIs ("10.1000/9912345678901234" is not an MMS ID)
    rest = _DOI.sub(" ", text)
    for match in _MMS_ID.finditer(rest):
        add(Identifier("mms_id", match.group(1)))
    rest = _MMS_ID.sub(" ", rest)
    for match in _ISBN.finditer(rest):
        if isbn := normalize_isbn(match.group(1)):
            add(Identifier("isbn", isbn))
    return found
