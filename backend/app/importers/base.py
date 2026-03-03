from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class RawRecord:
    """A raw record as received from an import source, before normalization."""
    data: dict
    source: str
    failed: bool = False
    error: Optional[str] = None


@dataclass
class CitationDraft:
    """
    Normalized citation data extracted from any import source.
    Maps 1:1 to the citations table schema.
    Fields are Optional — quality assessment determines which are missing.
    """
    title: Optional[str] = None
    resource_type: Optional[str] = None
    author: Optional[list[str]] = field(default_factory=list)
    editor: Optional[list[str]] = field(default_factory=list)
    year: Optional[int] = None
    publisher: Optional[str] = None
    place_of_publication: Optional[str] = None
    edition: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    isbn: Optional[str] = None
    issn: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    student_note: Optional[str] = None
    staff_note: Optional[str] = None

    # Import management fields (not stored on citation)
    section_title: Optional[str] = None

    def is_incomplete(self) -> bool:
        """Returns True if key fields are missing — used to gate AI enrichment."""
        required = [self.title, self.author, self.year]
        return not all(required)


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


class NormalizationError(Exception):
    """Raised when a raw record cannot be normalized to a CitationDraft."""
    pass


class ImportValidationError(Exception):
    """Raised when an import payload fails validation before processing begins."""
    pass
