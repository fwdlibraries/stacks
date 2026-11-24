"""Schemas for the authenticated (staff) reading list views."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.public import PublicCitation


class StaffCitation(PublicCitation):
    staff_note: str | None = None
    source_system: str | None = None
    source_identifier: str | None = None


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


class StaffReadingList(ReadingListSummary):
    sections: list[StaffSection] = []
