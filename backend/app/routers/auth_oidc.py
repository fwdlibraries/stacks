"""Single sign-on routes (OpenID Connect). See app/services/sso.py."""
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import SsoConfig
from app.routers.ingest import get_http_client
from app.services import sso, tenancy
from app.services.ephemeral import EphemeralStore, get_ephemeral_store

router = APIRouter()

LOGIN_CODE_TTL_SECONDS = 60


async def active_config(db: AsyncSession, tenant: tenancy.Tenant | None) -> SsoConfig | None:
    if tenant is None:
        return None
    return await db.scalar(
        select(SsoConfig).where(SsoConfig.organization_id == tenant.organization_id, SsoConfig.is_active.is_(True))
    )


class SsoInfo(BaseModel):
    enabled: bool
    label: str | None = None
    passwords_allowed: bool = True


@router.get("", response_model=SsoInfo, summary="Single sign-on for this site")
async def info(tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant), db: AsyncSession = Depends(get_db)):
    """Public: whether the sign-in page should offer the institution's sign-in."""
    config = await active_config(db, tenant)
    if config is None:
        return SsoInfo(enabled=False)
    return SsoInfo(enabled=True, label=config.button_label, passwords_allowed=not config.disable_passwords)


def _local(path: str | None) -> str:
    return path if path and path.startswith("/") and not path.startswith("//") else "/lists"


def _back_to_login(message: str) -> RedirectResponse:
    return RedirectResponse("/login?" + urlencode({"sso_error": message}), status_code=303)


@router.get("/start", summary="Begin single sign-on")
async def start(
    next: str | None = None,
    tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant),
    db: AsyncSession = Depends(get_db),
    store: EphemeralStore = Depends(get_ephemeral_store),
    http: httpx.AsyncClient = Depends(get_http_client),
):
    config = await active_config(db, tenant)
    if config is None:
        return _back_to_login("Single sign-on isn't set up for this site.")
    try:
        url = await sso.start(http, config, tenancy.base_url(tenant), _local(next), store)
    except sso.SsoError as exc:
        return _back_to_login(str(exc))
    return RedirectResponse(url, status_code=303)


@router.get("/callback", summary="Single sign-on callback")
async def callback(
    request: Request,
    tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant),
    db: AsyncSession = Depends(get_db),
    store: EphemeralStore = Depends(get_ephemeral_store),
    http: httpx.AsyncClient = Depends(get_http_client),
):
    params = request.query_params
    state = params.get("state")
    record = await store.pop(f"oidc:state:{state}") if state else None  # single use, even on failure
    if params.get("error"):
        reason = "You cancelled signing in." if params["error"] == "access_denied" else "Your institution's sign-in didn't complete."
        return _back_to_login(reason)
    config = await active_config(db, tenant)
    if record is None or config is None or record.get("org") != str(config.organization_id):
        return _back_to_login("That sign-in has expired or doesn't belong to this site. Try again.")
    if not params.get("code"):
        return _back_to_login("Your institution's sign-in didn't complete.")
    try:
        claims = await sso.finish(http, config, tenancy.base_url(tenant), params["code"], record)
        user = await sso.resolve_user(db, config, claims)
    except sso.SsoError as exc:
        await db.rollback()
        return _back_to_login(str(exc))
    code = secrets.token_urlsafe(32)
    # The same one-time code hand-off as LTI launches (/launch exchanges it for tokens)
    await store.put(f"lti:code:{code}", {"user_id": str(user.id), "next": record["next"], "method": "sso"}, LOGIN_CODE_TTL_SECONDS)
    return RedirectResponse(f"/launch?code={code}", status_code=303)
