from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.importers.base import CitationDraft, ImportHandler, RawRecord
from app.ingest import marc


class Z3950Handler(ImportHandler):
    """
    Z39.50 import via YAZ REST gateway sidecar.

    The YAZ gateway (running as a separate container) handles the Z39.50
    protocol. This handler communicates with it over HTTP, keeping the
    Python application insulated from protocol complexity.

    MARC records are parsed by app.ingest.marc (shared with the Alma resolver).

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
        record = marc.parse_marcxml(raw.data["marcxml"])
        draft = marc.to_draft(record)
        draft.metadata["marc_leader"] = str(record.leader)
        return draft
