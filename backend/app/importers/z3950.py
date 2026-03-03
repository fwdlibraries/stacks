from typing import AsyncIterator
import httpx
import pymarc
import io

from app.importers.base import ImportHandler, RawRecord, CitationDraft, NormalizationError
from app.config import settings


class Z3950Handler(ImportHandler):
    """
    Z39.50 import via YAZ REST gateway sidecar.

    The YAZ gateway (running as a separate container) handles the Z39.50
    protocol. This handler communicates with it over HTTP, keeping the
    Python application insulated from protocol complexity.

    MARC records are parsed via pymarc.

    Payload shape:
    {
        "host": "z3950.library.example.edu",
        "port": 210,
        "database": "INNOPAC",
        "query": "ti=introduction to sociology",
        "query_type": "ccl",   # or "cql"
        "limit": 20
    }
    """

    def __init__(self):
        self.gateway_url = settings.yaz_gateway_url

    async def fetch(self, payload: dict) -> AsyncIterator[RawRecord]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.gateway_url}/search",
                params={
                    "host": payload["host"],
                    "port": payload.get("port", 210),
                    "db": payload["database"],
                    "query": payload["query"],
                    "querytype": payload.get("query_type", "ccl"),
                    "maximumRecords": payload.get("limit", 20),
                    "recordSchema": "marcxml",
                },
            )
            response.raise_for_status()
            data = response.json()

        for record_xml in data.get("records", []):
            yield RawRecord(data={"marcxml": record_xml}, source="z3950")

    def normalize(self, raw: RawRecord) -> CitationDraft:
        try:
            marcxml = raw.data["marcxml"]
            record = pymarc.parse_xml_to_array(io.StringIO(marcxml))[0]
        except Exception as e:
            raise NormalizationError(f"Failed to parse MARC record: {e}")

        return CitationDraft(
            title=self._get_title(record),
            author=self._get_authors(record),
            editor=self._get_editors(record),
            year=self._get_year(record),
            publisher=self._get_publisher(record),
            place_of_publication=self._get_place(record),
            edition=self._get_field(record, "250", "a"),
            isbn=self._get_isbn(record),
            issn=self._get_field(record, "022", "a"),
            resource_type=self._infer_resource_type(record),
            metadata={
                "marc_leader": str(record.leader),
                "call_number": self._get_field(record, "050", "a"),
            },
        )

    def _get_title(self, record: pymarc.Record) -> str | None:
        f245 = record["245"]
        if not f245:
            return None
        title = f245.get("a", "")
        subtitle = f245.get("b", "")
        return f"{title} {subtitle}".strip().rstrip("/").strip() or None

    def _get_authors(self, record: pymarc.Record) -> list[str]:
        authors = []
        # Primary author
        for tag in ["100", "110", "111"]:
            field = record[tag]
            if field:
                name = field.get("a", "").rstrip(",").strip()
                if name:
                    authors.append(name)
                break
        # Additional authors
        for field in record.get_fields("700"):
            name = field.get("a", "").rstrip(",").strip()
            if name:
                authors.append(name)
        return authors

    def _get_editors(self, record: pymarc.Record) -> list[str]:
        editors = []
        for field in record.get_fields("700"):
            relator = field.get("e", "").lower()
            if "editor" in relator or "ed." in relator:
                name = field.get("a", "").rstrip(",").strip()
                if name:
                    editors.append(name)
        return editors

    def _get_year(self, record: pymarc.Record) -> int | None:
        f260 = record["260"] or record["264"]
        if f260:
            date_str = f260.get("c", "")
            digits = "".join(c for c in date_str if c.isdigit())
            if len(digits) >= 4:
                try:
                    return int(digits[:4])
                except ValueError:
                    pass
        return None

    def _get_publisher(self, record: pymarc.Record) -> str | None:
        f260 = record["260"] or record["264"]
        if f260:
            pub = f260.get("b", "").rstrip(",").strip()
            return pub or None
        return None

    def _get_place(self, record: pymarc.Record) -> str | None:
        f260 = record["260"] or record["264"]
        if f260:
            place = f260.get("a", "").rstrip(":").strip()
            return place or None
        return None

    def _get_isbn(self, record: pymarc.Record) -> str | None:
        f020 = record["020"]
        if f020:
            isbn = f020.get("a", "").split()[0].replace("-", "")
            return isbn or None
        return None

    def _get_field(self, record: pymarc.Record, tag: str, subfield: str) -> str | None:
        field = record[tag]
        if field:
            value = field.get(subfield, "").strip()
            return value or None
        return None

    def _infer_resource_type(self, record: pymarc.Record) -> str:
        leader = record.leader
        record_type = leader[6] if len(leader) > 6 else ""
        bib_level = leader[7] if len(leader) > 7 else ""

        if record_type == "a" and bib_level == "m":
            return "book"
        if record_type == "a" and bib_level == "s":
            return "journal_article"
        if record_type in ("g", "k", "o", "r"):
            return "av_media"
        return "other"
