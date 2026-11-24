"""MARC 21 → CitationDraft. Shared by the Alma resolver and the Z39.50 importer."""
import io
import re

import pymarc

from app.ingest.draft import CitationDraft, NormalizationError
from app.ingest.identifiers import normalize_doi, normalize_isbn

# ISBD punctuation that ends MARC subfields ("Title :", "Publisher,", "2017.")
_TRAILING_PUNCT = re.compile(r"[\s/:;,=]+$")
# ...but a final period after an initial or abbreviation is part of the text ("Evans, Richard J.", "2nd ed.")
_ABBREVIATION_END = re.compile(r"(?:^|[\s.])[A-Za-z]{1,3}\.$")


def parse_marcxml(marcxml: str) -> pymarc.Record:
    try:
        records = pymarc.parse_xml_to_array(io.StringIO(marcxml))
    except Exception as exc:
        raise NormalizationError(f"Failed to parse MARC record: {exc}") from exc
    if not records or records[0] is None:
        raise NormalizationError("MARC XML contained no record")
    return records[0]


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    value = _TRAILING_PUNCT.sub("", value.strip())
    while value.endswith(".") and not _ABBREVIATION_END.search(value):
        value = _TRAILING_PUNCT.sub("", value[:-1])
    return value or None


def _sub(record: pymarc.Record, tag: str, code: str) -> str | None:
    field = record.get(tag)
    return _clean(field.get(code)) if field else None


def _publication(record: pymarc.Record) -> pymarc.Field | None:
    # 264 second indicator 1 = publication (others are production, copyright, ...)
    for field in record.get_fields("264"):
        if field.indicator2 == "1":
            return field
    return record.get("260") or record.get("264")


def _is_editor(field: pymarc.Field) -> bool:
    relators = " ".join(field.get_subfields("e", "4")).lower()
    return "editor" in relators or "ed." in relators or "edt" in relators


def title(record: pymarc.Record) -> str | None:
    f245 = record.get("245")
    if not f245:
        return None
    main, subtitle = _clean(f245.get("a")), _clean(f245.get("b"))
    if main and subtitle:
        # "What is history? The …" rather than "What is history?: the …"
        return f"{main} {subtitle[0].upper()}{subtitle[1:]}" if main[-1] in "?!" else f"{main}: {subtitle}"
    return main or subtitle


def authors(record: pymarc.Record) -> list[str]:
    names: list[str] = []
    for tag in ("100", "110", "111"):
        if (field := record.get(tag)) and (name := _clean(field.get("a"))):
            names.append(name)
            break
    for field in record.get_fields("700", "710"):
        if not _is_editor(field) and (name := _clean(field.get("a"))) and name not in names:
            names.append(name)
    return names


def editors(record: pymarc.Record) -> list[str]:
    return [name for f in record.get_fields("700") if _is_editor(f) and (name := _clean(f.get("a")))]


def year(record: pymarc.Record) -> int | None:
    if (pub := _publication(record)) and (match := re.search(r"\d{4}", pub.get("c") or "")):
        return int(match.group())
    # 008/07-10: Date 1
    if (f008 := record.get("008")) and (data := f008.data) and data[7:11].isdigit():
        return int(data[7:11])
    return None


def isbn(record: pymarc.Record) -> str | None:
    for field in record.get_fields("020"):
        for value in field.get_subfields("a"):
            if normalized := normalize_isbn(value.split()[0]):
                return normalized
    return None


def doi(record: pymarc.Record) -> str | None:
    for field in record.get_fields("024"):
        if field.indicator1 == "7" and (field.get("2") or "").lower() == "doi":
            return normalize_doi(field.get("a") or "")
    return None


def is_electronic(record: pymarc.Record) -> bool:
    if (f008 := record.get("008")) and len(f008.data) > 23 and f008.data[23] in "oqs":
        return True
    return any("online resource" in (f.get("a") or "").lower() for f in record.get_fields("338"))


def resource_type(record: pymarc.Record) -> str:
    leader = str(record.leader)
    record_type, bib_level = leader[6:7], leader[7:8]
    if record_type in ("a", "t") and bib_level == "m":
        return "ebook" if is_electronic(record) else "book"
    if record_type == "a" and bib_level in ("a", "b"):
        return "journal_article"
    if record_type in ("g", "i", "j", "k", "o", "r"):
        return "av_media"
    return "other"


def to_draft(record: pymarc.Record) -> CitationDraft:
    pub = _publication(record)
    return CitationDraft(
        title=title(record),
        resource_type=resource_type(record),
        author=authors(record),
        editor=editors(record),
        year=year(record),
        publisher=_clean(pub.get("b")) if pub else None,
        place_of_publication=_clean(pub.get("a")) if pub else None,
        edition=_sub(record, "250", "a"),
        isbn=isbn(record),
        issn=_sub(record, "022", "a"),
        doi=doi(record),
        metadata={k: v for k, v in {"call_number": _sub(record, "050", "a")}.items() if v},
    )
