from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Defined with the ingest pipeline (shared by importers and resolvers); re-exported here
from app.ingest.draft import CitationDraft, NormalizationError  # noqa: F401


@dataclass
class RawRecord:
    """A raw record as received from an import source, before normalization."""
    data: dict
    source: str
    failed: bool = False
    error: str | None = None


class ImportHandler(ABC):
    """
    Base class for all citation import sources.
    Each handler implements fetch() and normalize().
    assess_quality() has a default implementation that can be overridden.
    """

    @abstractmethod
    async def fetch(self, payload: dict) -> AsyncIterator[RawRecord]:
        """
        Fetch raw records from the source.
        Yields RawRecord instances one at a time to support streaming and progress reporting.
        """
        ...

    @abstractmethod
    def normalize(self, raw: RawRecord) -> CitationDraft:
        """
        Normalize a raw record to the internal CitationDraft schema.
        Raises NormalizationError if the record is unrecoverable.
        """
        ...

    def assess_quality(self, draft: CitationDraft) -> tuple[float, list[str]]:
        """
        Returns (confidence_score, warnings[]).
        confidence_score: 0.0–1.0 based on completeness of key fields.
        warnings: list of missing/ambiguous field codes shown in review UI.
        """
        key_fields = {
            "title": draft.title,
            "author": draft.author,
            "year": draft.year,
            "resource_type": draft.resource_type,
        }
        recommended_fields = {
            "publisher": draft.publisher,
            "isbn": draft.isbn,
            "doi": draft.doi,
        }

        warnings = []

        for field_name, value in key_fields.items():
            if not value:
                warnings.append(f"missing_{field_name}")

        for field_name, value in recommended_fields.items():
            if not value:
                warnings.append(f"missing_{field_name}")

        # Score based on key fields only
        present = sum(1 for v in key_fields.values() if v)
        score = round(present / len(key_fields), 2)

        return score, warnings


class ImportValidationError(Exception):
    """Raised when an import payload fails validation before processing begins."""
    pass
