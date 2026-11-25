"""Organization administration: settings, library connections, link resolution.

Everything here needs settings.manage for the whole organization (an
Administrator assigned at organization scope). Domains are shown to them but
changed only by system admins: on a shared, hosted installation, letting an
organization claim any hostname would let it take another's address.
"""
import re
import uuid
from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_admin, require_permission
from app.ingest.candidate import SourceError
from app.ingest.identifiers import detect
from app.ingest.resolvers import ResolveContext, primo
from app.ingest.sources import SOURCE_CONFIGS, Source
from app.models.models import (
    Citation,
    LibrarySource,
    Organization,
    OrganizationDomain,
    ResourceType,
    User,
)
from app.routers.ingest import get_http_client
from app.services import credentials, resolution, tenancy

router = APIRouter()
manage_settings = require_permission("settings.manage")


# ── Organization ─────────────────────────────────────────────────────────────


class DomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    hostname: str
    is_primary: bool


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    address: str
    domains: list[DomainOut]
    # None: using the installation default (shown alongside)
    lms_origins: list[str] | None
    default_lms_origins: list[str]
    contact_email: str | None
    default_contact_email: str | None
    can_manage_domains: bool


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # [] = no LMS may frame Stacks; null = use the installation default
    lms_origins: list[str] | None = Field(default=None, max_length=50)
    contact_email: str | None = Field(default=None, max_length=254)


async def _organization_out(db: AsyncSession, user: User) -> OrganizationOut:
    org = await db.get(Organization, user.organization_id)
    tenant = await tenancy.tenant_for_org(db, org.id)
    domains = (
        await db.scalars(
            select(OrganizationDomain)
            .where(OrganizationDomain.organization_id == org.id)
            .order_by(OrganizationDomain.is_primary.desc(), OrganizationDomain.hostname)
        )
    ).all()
    return OrganizationOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        address=tenant.base_url,
        domains=[DomainOut.model_validate(d) for d in domains],
        lms_origins=tenant.settings.frame_ancestors,
        default_lms_origins=settings.frame_ancestors.split(),
        contact_email=tenant.settings.metadata_contact_email,
        default_contact_email=settings.metadata_contact_email or None,
        can_manage_domains=bool(user.is_system_admin),
    )


@router.get("/organization", response_model=OrganizationOut, summary="Organization settings")
async def get_organization(user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    return await _organization_out(db, user)


@router.patch("/organization", response_model=OrganizationOut, summary="Change organization settings")
async def update_organization(
    body: OrganizationUpdate, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)
):
    org = await db.get(Organization, user.organization_id)
    sent = body.model_fields_set
    if "name" in sent and body.name:
        org.name = body.name.strip()
    current = dict(org.settings or {})
    if "lms_origins" in sent:
        if body.lms_origins is None:
            current.pop("frame_ancestors", None)
        else:
            current["frame_ancestors"] = [o.strip() for o in body.lms_origins if o.strip()]
    if "contact_email" in sent:
        current["metadata_contact_email"] = body.contact_email or None
    try:
        org.settings = tenancy.OrgSettings.model_validate(current).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors()[0]["msg"]) from exc
    await db.flush()
    return await _organization_out(db, user)


class DomainCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hostname: str = Field(min_length=1, max_length=253)


@router.post("/organization/domains", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED,
             summary="Add a domain (system admins)")
async def add_domain(body: DomainCreate, user: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    host = tenancy.normalize_host(body.hostname)
    if not host:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a hostname, e.g. stacks.library.example.edu")
    existing = await db.scalar(select(OrganizationDomain).where(OrganizationDomain.hostname == host))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{host} is already in use")
    has_primary = await db.scalar(
        select(OrganizationDomain.id).where(
            OrganizationDomain.organization_id == user.organization_id, OrganizationDomain.is_primary.is_(True)
        )
    )
    db.add(OrganizationDomain(organization_id=user.organization_id, hostname=host, is_primary=not has_primary))
    await db.flush()
    return await _organization_out(db, user)


async def _own_domain(db: AsyncSession, user: User, domain_id: uuid.UUID) -> OrganizationDomain:
    domain = await db.get(OrganizationDomain, domain_id)
    if domain is None or domain.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    return domain


@router.post("/organization/domains/{domain_id}/primary", response_model=OrganizationOut,
             summary="Make a domain the public address (system admins)")
async def make_primary(domain_id: uuid.UUID, user: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    chosen = await _own_domain(db, user, domain_id)
    for domain in await db.scalars(
        select(OrganizationDomain).where(OrganizationDomain.organization_id == user.organization_id)
    ):
        domain.is_primary = domain.id == chosen.id
    await db.flush()
    return await _organization_out(db, user)


@router.delete("/organization/domains/{domain_id}", response_model=OrganizationOut, summary="Remove a domain (system admins)")
async def remove_domain(domain_id: uuid.UUID, user: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    await db.delete(await _own_domain(db, user, domain_id))
    await db.flush()
    return await _organization_out(db, user)


# ── Library connections ──────────────────────────────────────────────────────

SourceKind = Literal["alma", "primo", "libkey"]


class SourceOut(BaseModel):
    kind: SourceKind
    configured: bool
    is_active: bool = False
    config: dict = {}
    key_set: bool = False  # the key itself is never returned
    updated_at: datetime | None = None


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict
    # Write-only. Omit to keep the stored key (required when adding a connection)
    api_key: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class SourceTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Test values from the form before saving; omitted ones come from what's stored
    config: dict | None = None
    api_key: str | None = Field(default=None, max_length=500)


class TestResult(BaseModel):
    ok: bool
    message: str


def _validate_config(kind: str, config: dict):
    try:
        return SOURCE_CONFIGS[kind].model_validate(config)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ())) or "settings"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field}: {first['msg']}") from exc


async def _source(db: AsyncSession, user: User, kind: str) -> LibrarySource | None:
    return await db.scalar(
        select(LibrarySource).where(LibrarySource.organization_id == user.organization_id, LibrarySource.kind == kind)
    )


def _source_out(kind: str, row: LibrarySource | None) -> SourceOut:
    if row is None:
        return SourceOut(kind=kind, configured=False)
    return SourceOut(
        kind=kind, configured=True, is_active=row.is_active, config=row.config,
        key_set=bool(row.api_key_encrypted), updated_at=row.updated_at,
    )


@router.get("/sources", response_model=list[SourceOut], summary="Library connections")
async def list_sources(user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    return [_source_out(kind, await _source(db, user, kind)) for kind in ("alma", "primo", "libkey")]


@router.put("/sources/{kind}", response_model=SourceOut, summary="Add or change a library connection")
async def save_source(
    kind: SourceKind, body: SourceUpdate, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)
):
    config = _validate_config(kind, body.config)
    row = await _source(db, user, kind)
    key = (body.api_key or "").strip()
    if row is None and not key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the API key to add this connection")
    if row is None:
        row = LibrarySource(organization_id=user.organization_id, kind=kind)
        db.add(row)
    row.config = config.model_dump()
    row.is_active = body.is_active
    if key:
        row.api_key_encrypted = credentials.encrypt(key)
    await db.flush()
    await db.refresh(row)
    return _source_out(kind, row)


@router.delete("/sources/{kind}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a library connection")
async def delete_source(kind: SourceKind, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    row = await _source(db, user, kind)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not connected")
    await db.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def check_source(kind: str, source: Source, http: httpx.AsyncClient) -> TestResult:
    """One cheap, read-only call that proves the address and key work."""
    ctx = ResolveContext(http=http, sources={kind: source})
    try:
        if kind == "alma":
            # Ex Libris' per-area test endpoint answers (XML) when the key may read bibs
            resp = await http.get(
                f"{source.config.api_base}/almaws/v1/bibs/test",
                headers={"Authorization": f"apikey {source.api_key}"},
            )
            if resp.status_code == 200:
                code = re.search(r"institutionCode:\s*(\S+)", resp.text)
                where = f" for {code.group(1)}" if code else ""
                return TestResult(ok=True, message=f"Connected{where}: the key can read bibliographic records.")
            if resp.status_code in (400, 401, 403):
                return TestResult(
                    ok=False,
                    message="Alma refused the key: check the key, the region, and that it has Bibs (read) access.",
                )
            return TestResult(ok=False, message=f"Alma returned HTTP {resp.status_code}.")
        if kind == "primo":
            try:
                page = await primo.search_page(ctx, "any,contains,history", limit=1)
            except SourceError as exc:
                if "HTTP 400" in exc.message or "rejected" in exc.message:
                    return TestResult(
                        ok=False,
                        message="Primo refused the search: check the key, region, view ID, tab and scope.",
                    )
                raise
            return TestResult(ok=True, message=f"Connected: a test search found {page.total:,} results.")
        if kind == "libkey":
            resp = await http.get(
                f"https://public-api.thirdiron.com/public/v1/libraries/{source.config.library_id}/articles/doi/10.1038%2Fnature12373",
                params={"access_token": source.api_key},
            )
            if resp.status_code in (401, 403):
                return TestResult(ok=False, message="LibKey rejected the library ID or token.")
            if resp.status_code >= 500 or resp.status_code not in (200, 404):
                return TestResult(ok=False, message=f"LibKey returned HTTP {resp.status_code}.")
            return TestResult(ok=True, message="Connected: LibKey accepted the library ID and token.")
    except SourceError as exc:
        return TestResult(ok=False, message=str(exc))
    except httpx.HTTPError as exc:
        return TestResult(ok=False, message=f"Couldn't reach the service ({type(exc).__name__}).")
    return TestResult(ok=False, message="Unknown connection type")


@router.post("/sources/{kind}/test", response_model=TestResult, summary="Test a library connection")
async def test_source(
    kind: SourceKind,
    body: SourceTest,
    user: User = Depends(manage_settings),
    db: AsyncSession = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http_client),
):
    row = await _source(db, user, kind)
    config = _validate_config(kind, body.config if body.config is not None else (row.config if row else {}))
    key = (body.api_key or "").strip()
    if not key:
        if row is None or not row.api_key_encrypted:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the API key to test")
        try:
            key = credentials.decrypt(row.api_key_encrypted)
        except credentials.CredentialError:
            return TestResult(ok=False, message="The stored key can't be read (the encryption key changed). Enter it again.")
    return await check_source(kind, Source(kind=kind, config=config, api_key=key), http)


# ── Link resolution ──────────────────────────────────────────────────────────


class ResolutionSettingsOut(resolution.ResolutionConfig):
    # Which steps have what they need (LibKey: a connection; Alma: Primo + Alma settings)
    available: dict[str, bool]


@router.get("/link-resolution", response_model=ResolutionSettingsOut, summary="Link resolution settings")
async def get_link_resolution(user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    ctx = await resolution.load_context(db, user.organization_id)
    return ResolutionSettingsOut(
        **ctx.config.model_dump(),
        available={"libkey": ctx.libkey is not None, "alma": ctx.alma is not None, "open_access": True},
    )


@router.put("/link-resolution", response_model=ResolutionSettingsOut, summary="Change link resolution settings")
async def save_link_resolution(
    body: resolution.ResolutionConfig, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)
):
    if len(set(body.stack)) != len(body.stack):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Each step can appear once")
    org = await db.get(Organization, user.organization_id)
    org.link_resolver_settings = body.model_dump()
    await db.flush()
    return await get_link_resolution(user, db)


class TryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500, description="A DOI, ISBN or Alma MMS ID")


class TryStep(BaseModel):
    step: str
    outcome: str
    detail: str | None = None
    url: str | None = None


class TryResult(BaseModel):
    url: str | None
    resolved_by: str | None
    detail: str | None
    retracted: bool
    steps: list[TryStep]


@router.post("/link-resolution/try", response_model=TryResult, summary="Try the resolver stack on an identifier")
async def try_link_resolution(
    body: TryRequest,
    user: User = Depends(manage_settings),
    db: AsyncSession = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http_client),
):
    """Resolve as a student's click would right now (no cache), for an identifier."""
    idents = detect(body.query)
    if not idents:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a DOI, ISBN or Alma MMS ID")
    ident = idents[0]
    citation = Citation(id=uuid.uuid4(), title=body.query, metadata_={})
    if ident.kind == "doi":
        citation.resource_type, citation.doi = ResourceType.journal_article, ident.value
    elif ident.kind == "isbn":
        citation.resource_type, citation.isbn = ResourceType.book, ident.value
    else:
        citation.resource_type, citation.source_system, citation.source_identifier = (
            ResourceType.book, "alma", ident.value
        )
    ctx = await resolution.load_context(db, user.organization_id)
    trace = resolution.Trace()
    found = await resolution.resolve(citation, ctx, http, trace)
    return TryResult(
        url=found.url if found else None,
        resolved_by=found.step if found else None,
        detail=found.detail if found else None,
        retracted=bool(found and found.retracted),
        steps=[TryStep(step=s.step, outcome=s.outcome, detail=s.detail, url=s.url) for s in trace.steps],
    )
