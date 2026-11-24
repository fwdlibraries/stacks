"""Click-time link resolution: run the organization's resolver stack and send the
student straight to the resource.

Each step either finds a URL, finds nothing (the next step runs), or fails
(timeout or error: the next step runs). The render-time link from
app/services/links.py is always the last resort, so there's a link whenever
there was one before.

    libkey       direct article PDF/page (Third Iron), by DOI
    alma         the Alma link resolver's first available full-text service
    open_access  a legal open-access copy (OpenAlex), by DOI
    fallback     discovery record page, link-resolver menu, DOI or URL
"""
import asyncio
import hashlib
import json
import logging
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.ingest.sources import AlmaConfig, LibKeyConfig, PrimoConfig
from app.models.models import Citation, LibrarySource, Organization
from app.services import credentials, links

logger = logging.getLogger(__name__)

StepName = Literal["libkey", "alma", "open_access"]
DEFAULT_STACK: list[StepName] = ["libkey", "alma", "open_access"]


class ResolutionConfig(BaseModel):
    """Per-organization settings, stored in organizations.link_resolver_settings."""

    model_config = ConfigDict(extra="ignore")
    # Tried in order; steps whose source isn't configured are skipped. [] = plain links only
    stack: list[StepName] = Field(default_factory=lambda: list(DEFAULT_STACK))
    # How long a resolved link is reused. Longer: fewer API calls, less fresh
    cache_ttl_seconds: int = Field(default=6 * 3600, ge=0, le=7 * 86400)
    # A slow step is abandoned after this and the next one runs
    step_timeout_seconds: float = Field(default=2.5, ge=0.5, le=10)


@dataclass(frozen=True)
class AlmaResolver:
    base_url: str  # e.g. https://abc.alma.exlibrisgroup.com
    institution: str  # e.g. 01ABC_INST


@dataclass(frozen=True)
class LibKey:
    library_id: int
    token: str


@dataclass
class ResolutionContext:
    config: ResolutionConfig
    link_settings: links.LinkSettings | None = None
    alma: AlmaResolver | None = None
    libkey: LibKey | None = None
    # Changes when any setting changes, so cached links are dropped with it
    fingerprint: str = ""


@dataclass
class Resolution:
    url: str
    step: str  # a StepName or 'fallback'
    detail: str | None = None  # e.g. the package or platform
    retracted: bool = False


@dataclass
class StepReport:
    step: str
    outcome: Literal["found", "not_found", "error", "skipped"]
    detail: str | None = None
    url: str | None = None


@dataclass
class Trace:
    steps: list[StepReport] = field(default_factory=list)


async def load_context(db: AsyncSession, organization_id: uuid.UUID) -> ResolutionContext:
    org_settings = await db.scalar(
        select(Organization.link_resolver_settings).where(Organization.id == organization_id)
    )
    config = ResolutionConfig.model_validate(org_settings or {})
    rows = {
        row.kind: row
        for row in await db.scalars(
            select(LibrarySource).where(
                LibrarySource.organization_id == organization_id, LibrarySource.is_active.is_(True)
            )
        )
    }
    ctx = ResolutionContext(config=config)

    primo = None
    if row := rows.get("primo"):
        try:
            primo = PrimoConfig.model_validate(row.config)
            ctx.link_settings = links.LinkSettings.from_primo(primo)
        except ValueError:
            logger.warning("Invalid Primo settings for org %s", organization_id)

    alma = None
    if row := rows.get("alma"):
        try:
            alma = AlmaConfig.model_validate(row.config)
        except ValueError:
            logger.warning("Invalid Alma settings for org %s", organization_id)
    base = (alma and alma.resolver_url) or _alma_from_primo(primo)
    if base and primo:
        ctx.alma = AlmaResolver(base_url=base, institution=primo.institution)

    if (row := rows.get("libkey")) and row.api_key_encrypted:
        try:
            ctx.libkey = LibKey(
                library_id=LibKeyConfig.model_validate(row.config).library_id,
                token=credentials.decrypt(row.api_key_encrypted),
            )
        except (ValueError, credentials.CredentialError):
            logger.warning("LibKey settings for org %s can't be used", organization_id)

    stamp = {
        "config": config.model_dump(),
        "sources": {k: [r.config, str(r.updated_at)] for k, r in sorted(rows.items())},
    }
    ctx.fingerprint = hashlib.sha256(json.dumps(stamp, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return ctx


def _alma_from_primo(primo: PrimoConfig | None) -> str | None:
    # Ex Libris hosts both on the same customer prefix: abc.primo… / abc.alma…
    if primo and ".primo.exlibrisgroup.com" in primo.discovery_url:
        return primo.discovery_url.replace(".primo.exlibrisgroup.com", ".alma.exlibrisgroup.com")
    return None


# ── Steps ────────────────────────────────────────────────────────────────────


async def _libkey(citation: Citation, ctx: ResolutionContext, http: httpx.AsyncClient) -> Resolution | None:
    if not citation.doi or ctx.libkey is None:
        return None
    resp = await http.get(
        f"https://public-api.thirdiron.com/public/v1/libraries/{ctx.libkey.library_id}/articles/doi/{quote(citation.doi, safe='')}",
        params={"access_token": ctx.libkey.token},
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    if notice := data.get("retractionNoticeUrl"):
        # Send students to the retraction notice, as LibKey itself does
        return Resolution(notice, "libkey", "retraction notice", retracted=True)
    url = data.get("fullTextFile") or data.get("contentLocation")
    return Resolution(url, "libkey", "PDF" if data.get("fullTextFile") else "article page") if url else None


def _alma_params(citation: Citation) -> dict[str, str]:
    params = links.openurl_params(citation)
    if record_id := links.library_record_id(citation):
        # The resolver finds library records (including Network Zone ones) by MMS ID
        params["rft.mms_id"] = record_id.removeprefix("alma")
    params["svc_dat"] = "CTO"  # machine-readable list of services instead of the menu page
    return params


def first_full_text_service(xml_text: str) -> tuple[str, str | None] | None:
    """(resolution URL, package name) of the first usable full-text service in a CTO response."""
    root = ET.fromstring(xml_text)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    for service in root.iter():
        if local(service.tag) != "context_service" or service.get("service_type") != "getFullTxt":
            continue
        keys = {k.get("id"): (k.text or "") for k in service.iter() if local(k.tag) == "key"}
        # Filtered: the institution has no access through it; related: a different title
        if keys.get("Filtered") == "true" or keys.get("is_related_service") == "true":
            continue
        url = next((e.text for e in service.iter() if local(e.tag) == "resolution_url" and e.text), None)
        if url:
            return url, keys.get("package_public_name") or keys.get("package_display_name") or None
    return None


async def _alma(citation: Citation, ctx: ResolutionContext, http: httpx.AsyncClient) -> Resolution | None:
    if ctx.alma is None:
        return None
    params = _alma_params(citation)
    if not (params.get("rft.mms_id") or params.get("rft_id") or params.get("rft.isbn") or params.get("rft.issn")):
        return None  # nothing the resolver could match on
    resp = await http.get(f"{ctx.alma.base_url}/view/uresolver/{ctx.alma.institution}/openurl", params=params)
    resp.raise_for_status()
    found = first_full_text_service(resp.text)
    return Resolution(found[0], "alma", found[1]) if found else None


async def _open_access(citation: Citation, ctx: ResolutionContext, http: httpx.AsyncClient) -> Resolution | None:
    if not citation.doi:
        return None
    params = {"mailto": app_settings.metadata_contact_email} if app_settings.metadata_contact_email else {}
    resp = await http.get(f"https://api.openalex.org/works/doi:{quote(citation.doi, safe='/')}", params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    work = resp.json()
    if not (work.get("open_access") or {}).get("is_oa"):
        return None
    best = work.get("best_oa_location") or {}
    url = best.get("pdf_url") or best.get("landing_page_url") or work["open_access"].get("oa_url")
    source = (best.get("source") or {}).get("display_name")
    return Resolution(url, "open_access", source) if url else None


Step = Callable[[Citation, ResolutionContext, httpx.AsyncClient], Awaitable[Resolution | None]]
STEPS: dict[str, Step] = {"libkey": _libkey, "alma": _alma, "open_access": _open_access}


def _configured(step: str, ctx: ResolutionContext) -> bool:
    return {"libkey": ctx.libkey is not None, "alma": ctx.alma is not None}.get(step, True)


async def resolve(
    citation: Citation, ctx: ResolutionContext, http: httpx.AsyncClient, trace: Trace | None = None
) -> Resolution | None:
    """The first step that finds the resource, else the render-time fallback link."""
    for name in ctx.config.stack:
        if not _configured(name, ctx):
            if trace:
                trace.steps.append(StepReport(name, "skipped", "not set up"))
            continue
        try:
            found = await asyncio.wait_for(STEPS[name](citation, ctx, http), ctx.config.step_timeout_seconds)
        except TimeoutError:
            logger.info("Link step %s timed out for citation %s", name, citation.id)
            if trace:
                trace.steps.append(StepReport(name, "error", "timed out"))
            continue
        except Exception as exc:  # any failure moves on to the next step
            logger.info("Link step %s failed for citation %s: %s", name, citation.id, exc)
            if trace:
                trace.steps.append(StepReport(name, "error", type(exc).__name__))
            continue
        if found:
            if trace:
                trace.steps.append(StepReport(name, "found", found.detail, found.url))
            return found
        if trace:
            trace.steps.append(StepReport(name, "not_found"))

    fallback = links.citation_link(citation, ctx.link_settings)
    if trace:
        trace.steps.append(
            StepReport("fallback", "found" if fallback else "not_found", fallback.kind if fallback else None,
                       fallback.url if fallback else None)
        )
    return Resolution(fallback.url, "fallback", fallback.kind) if fallback else None


def cache_key(citation: Citation, ctx: ResolutionContext) -> str:
    # The citation's updated_at: editing it (new DOI, say) re-resolves immediately
    stamp = citation.updated_at.isoformat() if citation.updated_at else ""
    return f"go:{citation.id}:{stamp}:{ctx.fingerprint}"
