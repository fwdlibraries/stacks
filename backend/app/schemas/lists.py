"""Schemas for the authenticated (staff) reading list views."""
import uuid
from datetime import datetime
from typing import ClassVar, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.models import ResourceType
from app.schemas.public import PublicCitation


class StaffCitation(PublicCitation):
    staff_note: str | None = None
    source_system: str | None = None
    source_identifier: str | None = None
    # Bound: bibliographic fields come from the library's system and are read-only
    is_bound: bool = False
    match_method: str | None = None
    match_confidence: float | None = None
    source_status: str | None = None
    source_synced_at: datetime | None = None


class StaffSection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    sort_order: int
    citations: list[StaffCitation] = []


class ReadingListSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    visibility: str
    is_published: bool
    updated_at: datetime
    # What the current user may do with it (from their roles)
    can_edit: bool = False
    can_publish: bool = False


class StaffReadingList(ReadingListSummary):
    sections: list[StaffSection] = []


# ── Write schemas ────────────────────────────────────────────────────────────

Visibility = Literal["public", "institution", "unlisted"]


def _blank_to_none(value):
    """Treat empty or whitespace-only strings from forms as 'not set'."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Columns that are NOT NULL: a PATCH may omit them but not clear them
    _required_if_sent: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _reject_cleared_required_fields(self):
        for name in self._required_if_sent:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class ReadingListUpdate(_Input):
    _required_if_sent = ("title", "visibility")
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    visibility: Visibility | None = None

    _strip = field_validator("title", "description", mode="before")(_blank_to_none)


class SectionCreate(_Input):
    title: str = Field(min_length=1)
    description: str | None = None

    _strip = field_validator("title", "description", mode="before")(_blank_to_none)


class SectionUpdate(_Input):
    _required_if_sent = ("title",)
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None

    _strip = field_validator("title", "description", mode="before")(_blank_to_none)


class SectionReorder(_Input):
    section_ids: list[uuid.UUID]


class CitationReorder(_Input):
    citation_ids: list[uuid.UUID]


_CITATION_TEXT_FIELDS = (
    "title", "publisher", "place_of_publication", "edition", "volume", "issue", "pages",
    "isbn", "issn", "doi", "url", "student_note", "staff_note",
)


class _CitationFields(_Input):
    _required_if_sent = ("resource_type", "title", "is_required", "use_doi_for_linking")
    resource_type: ResourceType | None = None
    title: str | None = Field(default=None, min_length=1)
    is_required: bool | None = None
    author: list[str] | None = None
    editor: list[str] | None = None
    year: int | None = Field(default=None, ge=1000, le=2100)
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
    use_doi_for_linking: bool | None = None
    student_note: str | None = None
    staff_note: str | None = None
    metadata: dict | None = None

    _strip = field_validator(*_CITATION_TEXT_FIELDS, mode="before")(_blank_to_none)

    @field_validator("author", "editor", mode="before")
    @classmethod
    def _clean_names(cls, value):
        if value is None:
            return None
        names = [name.strip() for name in value if isinstance(name, str) and name.strip()]
        return names or None

    @field_validator("doi")
    @classmethod
    def _normalize_doi(cls, value: str | None):
        if value is None:
            return None
        for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
            if value.lower().startswith(prefix):
                value = value[len(prefix):]
        if not value.startswith("10."):
            raise ValueError("DOI should look like 10.1234/example")
        return value

    @field_validator("url")
    @classmethod
    def _http_url_only(cls, value: str | None):
        # Rendered as a link for students: only http(s) is safe (no javascript:, data:, ...)
        if value is not None and urlsplit(value).scheme.lower() not in ("http", "https"):
            raise ValueError("URL must start with http:// or https://")
        return value

    def to_model_fields(self) -> dict:
        """Fields the client actually sent, mapped to ORM attribute names."""
        data = self.model_dump(exclude_unset=True)
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata") or {}
        return data


class CitationCreate(_CitationFields):
    resource_type: ResourceType
    title: str = Field(min_length=1)


class CitationUpdate(_CitationFields):
    # Move to another section of the same reading list (appended at the end)
    list_section_id: uuid.UUID | None = None


# Fields staff may change on a citation bound to the library's system; everything
# else comes from the source record.
BOUND_EDITABLE_FIELDS = frozenset(
    {"is_required", "student_note", "staff_note", "use_doi_for_linking", "list_section_id"}
)
