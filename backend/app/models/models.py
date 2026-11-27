import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# ─── Enums ────────────────────────────────────────────────────────────────────

class ResourceType(str, enum.Enum):
    book = "book"
    book_chapter = "book_chapter"
    journal_article = "journal_article"
    ebook = "ebook"
    av_media = "av_media"
    website = "website"
    uploaded_file = "uploaded_file"
    other = "other"


class IdentityProvider(str, enum.Enum):
    local = "local"
    saml = "saml"
    google = "google"
    microsoft = "microsoft"
    oidc = "oidc"


class ScopeType(str, enum.Enum):
    organization = "organization"
    college = "college"
    department = "department"
    course_template = "course_template"
    course_offering = "course_offering"


# ─── Organization Hierarchy ───────────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    lti_issuer: Mapped[str | None] = mapped_column(Text)
    ai_settings: Mapped[dict] = mapped_column(JSONB, default={"enabled": False, "provider": None, "features": []})
    link_resolver_settings: Mapped[dict] = mapped_column(JSONB, default={})
    # Per-organization settings (app/services/tenancy.py OrgSettings): LMS origins
    # allowed to frame Stacks, contact address for open metadata APIs, ...
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    colleges: Mapped[list["College"]] = relationship(back_populates="organization")
    users: Mapped[list["User"]] = relationship(back_populates="organization")
    domains: Mapped[list["OrganizationDomain"]] = relationship(back_populates="organization")


class OrganizationDomain(Base):
    """A hostname that serves an organization (e.g. stacks.library.example.edu).

    Requests are attributed to an organization by their Host header. The primary
    domain is the organization's public address: LTI redirect URIs and tool URLs
    are built from it."""
    __tablename__ = "organization_domains"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hostname: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # lowercase, no port
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped[Organization] = relationship(back_populates="domains")


class College(Base):
    __tablename__ = "colleges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="colleges")
    departments: Mapped[list["Department"]] = relationship(back_populates="college")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    college_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)

    college: Mapped[College] = relationship(back_populates="departments")
    course_templates: Mapped[list["CourseTemplate"]] = relationship(back_populates="department")


class CourseTemplate(Base):
    __tablename__ = "course_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    department: Mapped[Department] = relationship(back_populates="course_templates")
    offerings: Mapped[list["CourseOffering"]] = relationship(back_populates="template")
    reading_lists: Mapped[list["ReadingList"]] = relationship(back_populates="course_template")


class Term(Base):
    """A teaching term (app/services/terms.py). `code` is what offerings and student URLs
    use: the SIS term code where there is one (e.g. 202710), else a slug (fall-2027)."""
    __tablename__ = "terms"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_terms_organization_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    # When rollover copies lists for this term, and when lists are due for review
    rollover_on: Mapped[date | None] = mapped_column(Date)
    lists_due_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CourseOffering(Base):
    """A course in one term: a live section, usually one LMS course shell."""
    __tablename__ = "course_offerings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("course_templates.id"), nullable=False)
    # Term.code (kept as text: student URLs use it); term_id links the Term record
    term: Mapped[str] = mapped_column(Text, nullable=False)
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id"), index=True)
    section: Mapped[str | None] = mapped_column(Text)
    # The LMS course shell's code (LTI context label), e.g. 40112.202710
    lms_code: Mapped[str | None] = mapped_column(Text, index=True)
    lti_context_id: Mapped[str | None] = mapped_column(Text)
    lti_deployment_id: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    template: Mapped[CourseTemplate] = relationship(back_populates="offerings")
    term_record: Mapped["Term | None"] = relationship()


# ─── Reading Lists ─────────────────────────────────────────────────────────────

class ReadingList(Base):
    __tablename__ = "reading_lists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("course_templates.id"), nullable=False)
    # 'course': shared by every term of the course (lists made before terms had their own)
    # 'section': one offering's list (course_offering_id); 'primary': a course variant's primary
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="course", server_default="course")
    course_offering_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_offerings.id"), index=True
    )
    # Where this list was copied from (rollover); kept if the source is deleted
    copied_from_list_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reading_lists.id", ondelete="SET NULL")
    )
    copied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(Text, nullable=False, default="Course Reading List")
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="public")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    course_template: Mapped[CourseTemplate] = relationship(back_populates="reading_lists")
    offering: Mapped["CourseOffering | None"] = relationship()
    sections: Mapped[list["ListSection"]] = relationship(back_populates="reading_list", order_by="ListSection.sort_order")


class ListSection(Base):
    __tablename__ = "list_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reading_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reading_lists.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The same item across copies of a list (rollover): reports and links follow it
    item_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )

    reading_list: Mapped[ReadingList] = relationship(back_populates="sections")
    citations: Mapped[list["Citation"]] = relationship(back_populates="section", order_by="Citation.sort_order")


class OfferingListOverride(Base):
    __tablename__ = "offering_list_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_offering_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("course_offerings.id"), nullable=False)
    reading_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reading_lists.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    instructor_note: Mapped[str | None] = mapped_column(Text)


# ─── Citations ────────────────────────────────────────────────────────────────

class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("list_sections.id"), nullable=False)
    resource_type: Mapped[ResourceType] = mapped_column(SAEnum(ResourceType), nullable=False)
    # The same item across copies of a list (rollover): reports and links follow it
    item_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )

    # Universal fields
    title: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)

    # Bibliographic fields
    author: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    editor: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    year: Mapped[int | None] = mapped_column(Integer)
    publisher: Mapped[str | None] = mapped_column(Text)
    place_of_publication: Mapped[str | None] = mapped_column(Text)
    edition: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[str | None] = mapped_column(Text)
    issue: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[str | None] = mapped_column(Text)
    isbn: Mapped[str | None] = mapped_column(Text)
    issn: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text, index=True)
    url: Mapped[str | None] = mapped_column(Text)

    # Linking
    openurl: Mapped[str | None] = mapped_column(Text)
    link_resolver_url: Mapped[str | None] = mapped_column(Text)
    use_doi_for_linking: Mapped[bool] = mapped_column(Boolean, default=True)

    # Import provenance — raw_import_data is never discarded
    source_system: Mapped[str | None] = mapped_column(Text)
    source_identifier: Mapped[str | None] = mapped_column(Text)
    raw_import_data: Mapped[dict | None] = mapped_column(JSONB)

    # Binding to the source record (see app/ingest). How the record was matched and
    # how sure that match is; a later AI resolver reports through the same fields.
    match_method: Mapped[str | None] = mapped_column(Text)        # 'identifier' | 'search' | ...
    match_confidence: Mapped[float | None] = mapped_column(Float)  # 0.0–1.0
    # None/'ok' while the source record is live; set by the catalogue sync:
    # 'missing' (gone from Alma) | 'suppressed' (hidden from discovery);
    # 'unlinked' when staff detached the citation to edit it locally
    source_status: Mapped[str | None] = mapped_column(Text)
    source_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Type-specific overflow metadata
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default={})

    # Notes
    staff_note: Mapped[str | None] = mapped_column(Text)   # internal only
    student_note: Mapped[str | None] = mapped_column(Text) # visible to students

    # File reference (uploaded_file type only)
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("uploaded_files.id"))

    # AI extensibility
    ai_enrichment_status: Mapped[str] = mapped_column(Text, default="pending")

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    section: Mapped[ListSection] = relationship(back_populates="citations")

    @property
    def is_bound(self) -> bool:
        """Bibliographic fields come from (and are kept in sync with) the library's system."""
        from app.ingest.candidate import AUTHORITATIVE_SOURCES
        return self.source_system in AUTHORITATIVE_SOURCES and self.source_status != "unlinked"


# ─── Single sign-on ───────────────────────────────────────────────────────────

class SsoConfig(Base):
    """An organization's OpenID Connect sign-in (app/services/sso.py). One per organization."""
    __tablename__ = "sso_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # The provider's issuer, e.g. https://login.microsoftonline.com/<tenant id>/v2.0
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    button_label: Mapped[str] = mapped_column(Text, nullable=False, default="Sign in with your institution")
    # Emails in these domains may match invitations or create accounts
    allowed_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    # Create an account (with no roles) on first sign-in; otherwise invited people only
    allow_signup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Require the provider to say multi-factor authentication was used (amr claim)
    require_mfa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Turn off email-and-password sign-in for this organization (system admins excepted)
    disable_passwords: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Provider role claim value → Stacks role, granted organization-wide, e.g.
    # {"Stacks.Librarian": "Librarian"}; kept in step at each sign-in
    role_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─── Library sources (discovery / catalogue connections) ──────────────────────

class LibrarySource(Base):
    """An org's connection to a library system (Alma, Primo). One per kind per org.

    `config` holds non-secret settings (API host, institution, view); the API key
    is stored encrypted (app/services/credentials.py) and never returned by the API.
    """
    __tablename__ = "library_sources"
    __table_args__ = (UniqueConstraint("organization_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'alma' | 'primo'
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─── Citation history ─────────────────────────────────────────────────────────

class CitationEvent(Base):
    """What happened to a citation outside of staff edits, mainly the catalogue sync:
    'updated' (details: {field: [old, new]}), 'missing', 'suppressed', 'restored'."""
    __tablename__ = "citation_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    citation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("citations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_system: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


# ─── Link clicks ──────────────────────────────────────────────────────────────

class LinkClick(Base):
    """One student click on a citation link (via /go). Deliberately anonymous:
    no user, IP address or browser details, only what instructors' stats need."""
    __tablename__ = "link_clicks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    citation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("citations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reading_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reading_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Which resolver answered: 'libkey' | 'alma' | 'open_access' | 'fallback'
    resolved_by: Mapped[str | None] = mapped_column(Text)


# ─── Uploaded Files ───────────────────────────────────────────────────────────

class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)

    copyright_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    copyright_acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    copyright_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    copyright_statement: Mapped[str | None] = mapped_column(Text)

    extracted_text: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Users & Identity ─────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    given_name: Mapped[str | None] = mapped_column(Text)
    family_name: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set when an administrator invited this person: their first single sign-on with
    # this (verified) email links to this account. Nothing else links by email.
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", name="fk_users_invited_by"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization: Mapped[Organization] = relationship(back_populates="users")
    identities: Mapped[list["UserIdentity"]] = relationship(back_populates="user")
    # user_role_assignments has two FKs to users (user_id, granted_by); name the one this follows
    role_assignments: Mapped[list["UserRoleAssignment"]] = relationship(
        back_populates="user", foreign_keys="UserRoleAssignment.user_id"
    )


class UserIdentity(Base):
    __tablename__ = "user_identities"
    # One external identity belongs to one account
    __table_args__ = (UniqueConstraint("provider", "provider_user_id", name="uq_user_identities_provider_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[IdentityProvider] = mapped_column(SAEnum(IdentityProvider), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_email: Mapped[str | None] = mapped_column(Text)
    provider_metadata: Mapped[dict] = mapped_column(JSONB, default={})
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="identities")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "stk_live_abc123"
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=[])
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ─── Roles & Permissions ──────────────────────────────────────────────────────

class Role(Base):
    __tablename__ = "roles"
    # Built-in roles (no organization) are shared by name; organizations may add their own later
    __table_args__ = (
        Index("uq_roles_builtin_name", "name", unique=True, postgresql_where=text("organization_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    permissions: Mapped[list["Permission"]] = relationship(secondary="role_permissions", back_populates="roles")
    assignments: Mapped[list["UserRoleAssignment"]] = relationship(back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)

    roles: Mapped[list[Role]] = relationship(secondary="role_permissions", back_populates="permissions")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"
    __table_args__ = (UniqueConstraint("user_id", "role_id", "scope_type", "scope_id", name="uq_user_role_assignments_grant"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    scope_type: Mapped[ScopeType] = mapped_column(SAEnum(ScopeType), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    # 'sso': kept in step with the identity provider's role claims at each sign-in
    # (added and removed); anything else was granted in Stacks and is left alone
    source: Mapped[str | None] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="role_assignments", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(back_populates="assignments")


# ─── LTI ──────────────────────────────────────────────────────────────────────

class LtiPlatform(Base):
    __tablename__ = "lti_platforms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    auth_login_url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_token_url: Mapped[str] = mapped_column(Text, nullable=False)
    jwks_url: Mapped[str] = mapped_column(Text, nullable=False)
    # TODO: encrypt like library API keys (app/services/credentials.py). Plain PEM today;
    # only the public key is used so far (published at /lti/jwks).
    tool_private_key: Mapped[str] = mapped_column(Text, nullable=False)
    tool_public_key: Mapped[str] = mapped_column(Text, nullable=False)
    tool_key_id: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Which LMS this is ('brightspace' | 'canvas' | 'moodle' | other), learned from
    # launches (tool_platform claim); lets "match LMS" theming pick the right look
    product_family: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    deployments: Mapped[list["LtiDeployment"]] = relationship(back_populates="platform")


class LtiDeployment(Base):
    __tablename__ = "lti_deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lti_platforms.id"), nullable=False)
    deployment_id: Mapped[str] = mapped_column(Text, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    label: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    platform: Mapped[LtiPlatform] = relationship(back_populates="deployments")
    context_mappings: Mapped[list["LtiContextMapping"]] = relationship(back_populates="deployment")


class LtiContextMapping(Base):
    __tablename__ = "lti_context_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lti_deployments.id"), nullable=False)
    lti_context_id: Mapped[str] = mapped_column(Text, nullable=False)
    lti_context_label: Mapped[str | None] = mapped_column(Text)
    lti_context_title: Mapped[str | None] = mapped_column(Text)
    course_offering_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("course_offerings.id"))
    last_launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    deployment: Mapped[LtiDeployment] = relationship(back_populates="context_mappings")


class LtiDeepLink(Base):
    __tablename__ = "lti_deep_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lti_deployments.id"), nullable=False)
    resource_link_id: Mapped[str] = mapped_column(Text, nullable=False)
    reading_list_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reading_lists.id"))
    list_section_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("list_sections.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LtiUserMapping(Base):
    __tablename__ = "lti_user_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lti_platforms.id"), nullable=False)
    lti_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ─── Background Jobs & Webhooks ───────────────────────────────────────────────

class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    import_items: Mapped[list["ImportItem"]] = relationship(back_populates="job")


class ImportItem(Base):
    __tablename__ = "import_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_identifier: Mapped[str | None] = mapped_column(Text)
    normalized_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column()
    warnings: Mapped[list] = mapped_column(JSONB, default=[])
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    reviewed_data: Mapped[dict | None] = mapped_column(JSONB)
    target_section_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("list_sections.id"))
    resulting_citation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("citations.id"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped[BackgroundJob] = relationship(back_populates="import_items")


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    secret: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
