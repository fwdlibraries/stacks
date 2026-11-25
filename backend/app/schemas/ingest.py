"""Schemas for citation lookup and import from a source."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.lists import _blank_to_none


class LookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000, description="A DOI, ISBN or MMS ID, or text containing them")


class IdentifierOut(BaseModel):
    kind: Literal["doi", "isbn", "mms_id"]
    value: str


class CandidateCitation(BaseModel):
    """The citation a candidate would create (bibliographic fields only)."""

    title: str | None = None
    resource_type: str | None = None
    author: list[str] = []
    editor: list[str] = []
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
    metadata: dict = {}


class CandidateOut(BaseModel):
    @classmethod
    def from_candidate(cls, candidate) -> "CandidateOut":
        import dataclasses

        draft = {k: v for k, v in dataclasses.asdict(candidate.draft).items() if k in CandidateCitation.model_fields}
        return cls(
            source_system=candidate.source_system,
            source_identifier=candidate.source_identifier,
            match_method=candidate.match_method,
            confidence=candidate.confidence,
            authoritative=candidate.authoritative,
            availability=candidate.availability,
            citation=CandidateCitation.model_validate({k: v for k, v in draft.items() if v is not None}),
        )

    source_system: str
    source_identifier: str
    match_method: str
    confidence: float
    authoritative: bool
    # Search results: 'online' | 'in_library' | 'check_holdings' | 'citation_only'
    availability: str | None = None
    citation: CandidateCitation


class LookupResponse(BaseModel):
    identifiers: list[IdentifierOut]
    candidates: list[CandidateOut]
    # Sources that failed (unreachable, key rejected): shown, but not fatal
    warnings: list[str]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    offset: int = Field(default=0, ge=0, le=2000)
    limit: int = Field(default=10, ge=1, le=25)


class SearchResponse(BaseModel):
    total: int
    offset: int
    candidates: list[CandidateOut]


class IngestCapabilities(BaseModel):
    """What the add-citation dialog can offer this organization."""

    library_search: bool


class CitationFromSource(BaseModel):
    """Add a citation from a candidate. Only the binding is sent: the server fetches
    the record itself, so the stored metadata is always the source's."""

    model_config = ConfigDict(extra="forbid")
    source_system: str = Field(min_length=1, max_length=40)
    source_identifier: str = Field(min_length=1, max_length=300)
    is_required: bool = True
    student_note: str | None = None
    staff_note: str | None = None

    _strip = field_validator("student_note", "staff_note", mode="before")(_blank_to_none)


