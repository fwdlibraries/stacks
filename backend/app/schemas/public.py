"""Response schemas for the unauthenticated student list view.

These deliberately omit staff-only fields (staff_note, raw_import_data,
created_by, ...). Add fields here only if students may see them.
"""
import uuid

from pydantic import BaseModel, ConfigDict, Field


class PublicCitation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_type: str
    title: str
    sort_order: int
    is_required: bool

    author: list[str] | None = None
    editor: list[str] | None = None
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

    openurl: str | None = None
    link_resolver_url: str | None = None
    use_doi_for_linking: bool = True
    # Built per request from the org's discovery settings (app/services/links.py), never stored
    link_url: str | None = None
    link_kind: str | None = None  # 'library_record' | 'full_text' | 'doi' | 'web'

    student_note: str | None = None
    # The ORM attribute is `metadata_` (SQLAlchemy reserves `metadata`)
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")


class PublicSection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    sort_order: int
    citations: list[PublicCitation] = []


class PublicReadingList(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    visibility: str
    is_published: bool
    sections: list[PublicSection] = []
