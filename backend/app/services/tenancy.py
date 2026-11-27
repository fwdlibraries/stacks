"""Which organization a request belongs to, and that organization's settings.

Stacks runs the same way self-hosted and as a hosted, multi-tenant service: a
self-hosted install is simply one with a single organization.

- A request's organization comes from its Host header (organization_domains).
  Hosts that match none fall back to DEFAULT_ORGANIZATION if set; with
  REQUIRE_KNOWN_HOST they're refused (404) instead.
- Per-organization settings live in organizations.settings (OrgSettings). Each
  falls back to the installation-wide value from the environment when unset,
  so an install with no domains or settings behaves as configured in .env.
"""
import re
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import LtiPlatform, Organization, OrganizationDomain

_ORIGIN = re.compile(r"^https?://(\*\.)?[A-Za-z0-9.-]+(:\d{1,5})?$")
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


class OrgSettings(BaseModel):
    """organizations.settings. Unset values fall back to the environment."""

    model_config = ConfigDict(extra="ignore")
    # LMS origins allowed to frame Stacks, e.g. ["https://lms.example.edu"]
    frame_ancestors: list[str] | None = None
    # Sent to Crossref and OpenAlex with lookups ("polite pool")
    metadata_contact_email: str | None = None
    # Look and feel (theme.ThemeSettings, validated when saved) and logo
    # ({content_type, data: base64}); kept here so saving other settings keeps them
    theme: dict | None = None
    logo: dict | None = None
    # How live LMS course shells are coded, e.g. "{crn}.{term}" (app/services/terms.py)
    section_code_pattern: str | None = None
    # How rollover reads imports and primary codes (rollover.RolloverSettings, validated when saved)
    rollover: dict | None = None

    @field_validator("section_code_pattern")
    @classmethod
    def _pattern(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        from app.services.terms import compile_pattern  # terms imports this module

        compile_pattern(value.strip())  # PatternError is a ValueError
        return value.strip()

    @field_validator("frame_ancestors")
    @classmethod
    def _origins(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        bad = [v for v in value if not _ORIGIN.match(v)]
        if bad:
            raise ValueError(f"LMS origins must look like https://lms.example.edu: {bad}")
        return list(dict.fromkeys(value))

    @field_validator("metadata_contact_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value.strip()):
            raise ValueError("Enter an email address")
        return value.strip()


def normalize_host(value: str) -> str | None:
    """'Stacks.Example.edu:443.' → 'stacks.example.edu'; None if it isn't a hostname."""
    host = (value or "").strip().lower()
    if host.startswith("["):  # IPv6 literal
        return None
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    host = host.rstrip(".")
    return host if _HOSTNAME.match(host) else None


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    slug: str
    name: str
    primary_host: str | None
    settings: OrgSettings
    # True when the request's host is one of this organization's domains (not the
    # DEFAULT_ORGANIZATION fallback): then it serves only this organization
    by_domain: bool = False

    @property
    def base_url(self) -> str:
        """Where browsers reach this organization's Stacks."""
        if self.primary_host:
            return f"https://{self.primary_host}"
        return settings.public_base_url.rstrip("/")

    @property
    def frame_ancestors(self) -> list[str]:
        if self.settings.frame_ancestors is not None:
            return self.settings.frame_ancestors
        return settings.frame_ancestors.split()

    @property
    def contact_email(self) -> str | None:
        return self.settings.metadata_contact_email or settings.metadata_contact_email or None


def frame_policy(tenant: Tenant | None) -> str:
    origins = tenant.frame_ancestors if tenant else settings.frame_ancestors.split()
    return " ".join(["frame-ancestors", "'self'", *origins])


def page_policy(tenant: Tenant | None) -> str:
    """Content-Security-Policy for Stacks' pages: everything from Stacks itself, framed
    only by the organization's LMS. Contains custom theme CSS too: it can't load
    images, fonts or anything else from elsewhere, so it can't send data out."""
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            # React and some components set inline style attributes
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            frame_policy(tenant),
        ]
    )


def base_url(tenant: Tenant | None) -> str:
    return tenant.base_url if tenant else settings.public_base_url.rstrip("/")


async def _tenant(db: AsyncSession, org: Organization, by_domain: bool = False) -> Tenant:
    primary = await db.scalar(
        select(OrganizationDomain.hostname)
        .where(OrganizationDomain.organization_id == org.id)
        .order_by(OrganizationDomain.is_primary.desc(), OrganizationDomain.created_at)
        .limit(1)
    )
    return Tenant(
        organization_id=org.id,
        slug=org.slug,
        name=org.name,
        primary_host=primary,
        settings=OrgSettings.model_validate(org.settings or {}),
        by_domain=by_domain,
    )


async def tenant_for_org(db: AsyncSession, organization_id: uuid.UUID) -> Tenant | None:
    org = await db.get(Organization, organization_id)
    return await _tenant(db, org) if org else None


async def tenant_for_host(db: AsyncSession, host: str | None) -> Tenant | None:
    """The organization serving this hostname, else the default one (if configured)."""
    hostname = normalize_host(host or "")
    org = None
    if hostname:
        org = await db.scalar(
            select(Organization)
            .join(OrganizationDomain, OrganizationDomain.organization_id == Organization.id)
            .where(OrganizationDomain.hostname == hostname)
        )
    if org is not None:
        return await _tenant(db, org, by_domain=True)
    if settings.default_organization:
        org = await db.scalar(
            select(Organization).where(func.lower(Organization.slug) == settings.default_organization.lower())
        )
    return await _tenant(db, org) if org else None


async def get_tenant(request: Request, db: AsyncSession = Depends(get_db)) -> Tenant | None:
    """Dependency: the request's organization. None when no organization claims the host
    (self-hosted with nothing configured); 404 instead under REQUIRE_KNOWN_HOST."""
    tenant = await tenant_for_host(db, request.headers.get("host"))
    if tenant is None and settings.require_known_host:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return tenant


async def lms_family(db: AsyncSession, organization_id: uuid.UUID) -> str | None:
    """The kind of LMS the organization launches Stacks from (for 'match LMS: auto')."""
    return await db.scalar(
        select(LtiPlatform.product_family)
        .where(
            LtiPlatform.organization_id == organization_id,
            LtiPlatform.is_active.is_(True),
            LtiPlatform.product_family.is_not(None),
        )
        .order_by(LtiPlatform.created_at.desc())
        .limit(1)
    )
