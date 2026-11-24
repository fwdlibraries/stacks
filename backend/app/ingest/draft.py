"""The normalized citation shape every source produces."""
from dataclasses import dataclass, field


@dataclass
class CitationDraft:
    """
    Normalized citation data extracted from any import source.
    Maps 1:1 to the citations table schema.
    Fields are Optional — quality assessment determines which are missing.
    """
    title: str | None = None
    resource_type: str | None = None
    author: list[str] | None = field(default_factory=list)
    editor: list[str] | None = field(default_factory=list)
    year: int | None = None
    publisher: str | None = None
    place_of_publication: str | None = None
    edition: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    isbn: str | None = None
    issn: str | None = None
    doi: str | None = None
    url: str | None = None
    metadata: dict = field(default_factory=dict)
    student_note: str | None = None
    staff_note: str | None = None

    # Import management fields (not stored on citation)
    section_title: str | None = None

    def is_incomplete(self) -> bool:
        """Returns True if key fields are missing — used to gate AI enrichment."""
        required = [self.title, self.author, self.year]
        return not all(required)


class NormalizationError(Exception):
    """Raised when a raw record cannot be normalized to a CitationDraft."""
    pass
