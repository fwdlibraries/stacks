"""LTI 1.3 endpoints. Unversioned: URLs are registered in each LMS and must stay stable.

Flow: LMS → /lti/login (OIDC initiation) → LMS auth → POST /lti/launch (id_token)
→ staff: /launch?code=… in the editor SPA, which exchanges the one-time code for
tokens (POST /api/v1/auth/lti/exchange); students: the public list page.
"""
import html
import logging
import secrets
import uuid

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import LtiPlatform, ScopeType
from app.services import access, tenancy
from app.services import lti_service as lti
from app.services.ephemeral import EphemeralStore, get_ephemeral_store

logger = logging.getLogger(__name__)
router = APIRouter()

STATE_TTL_SECONDS = 300
LOGIN_CODE_TTL_SECONDS = 60


def launch_url(tenant: tenancy.Tenant | None = None) -> str:
    """The redirect URI registered with the LMS: the organization's address + /lti/launch."""
    return f"{tenancy.base_url(tenant)}/lti/launch"


def _wrong_site(host_tenant: tenancy.Tenant | None, organization_id) -> bool:
    """A launch arriving at another organization's hostname."""
    return bool(host_tenant and host_tenant.by_domain and host_tenant.organization_id != organization_id)


WRONG_SITE = "This LMS is registered with a different Stacks site. Check the tool's URLs in your LMS."


def _error_page(message: str, status_code: int = 400, tenant: tenancy.Tenant | None = None) -> HTMLResponse:
    """Plain page shown inside the LMS frame when a launch can't proceed."""
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Stacks</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
         background: #F5F7FA; color: #1B2433; margin: 0; padding: 3rem 1.5rem; line-height: 1.55; }}
  main {{ max-width: 32rem; margin: 0 auto; background: #FFFFFF; border: 1px solid #E3E7ED;
          border-radius: 8px; padding: 1.5rem 1.75rem; }}
  h1 {{ font-weight: 650; font-size: 1.375rem; letter-spacing: -0.01em; margin-top: 0; }}
</style></head>
<body><main><h1>Stacks couldn't open</h1><p>{html.escape(message)}</p></main></body></html>"""
    # Shown inside the LMS frame: allow the organization's LMS origins
    return HTMLResponse(
        body, status_code=status_code, headers={"Content-Security-Policy": tenancy.page_policy(tenant)}
    )


async def _params(request: Request) -> dict:
    """OIDC initiation may arrive as GET (query) or POST (form)."""
    if request.method == "POST":
        return dict(await request.form())
    return dict(request.query_params)


@router.api_route("/login", methods=["GET", "POST"], summary="LTI OIDC login initiation")
async def lti_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    store: EphemeralStore = Depends(get_ephemeral_store),
    host_tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant),
):
    """
    Step 1 of the LTI 1.3 launch: store a single-use state and nonce, then send the
    browser to the platform's OIDC auth endpoint.
    """
    params = await _params(request)
    try:
        platform = await lti.find_platform(db, params.get("iss"), params.get("client_id"))
        if not params.get("login_hint"):
            raise lti.LaunchError("The LMS login request is missing login_hint.")
        if _wrong_site(host_tenant, platform.organization_id):
            raise lti.LaunchError(WRONG_SITE)
    except lti.LaunchError as exc:
        return _error_page(str(exc), tenant=host_tenant)
    tenant = await tenancy.tenant_for_org(db, platform.organization_id)

    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    await store.put(f"lti:state:{state}", {"nonce": nonce, "platform_id": str(platform.id)}, STATE_TTL_SECONDS)
    url = lti.auth_request_url(
        platform,
        redirect_uri=launch_url(tenant),
        login_hint=params["login_hint"],
        lti_message_hint=params.get("lti_message_hint"),
        state=state,
        nonce=nonce,
    )
    return RedirectResponse(url, status_code=302)


@router.post("/launch", summary="LTI resource link launch")
async def lti_launch(
    request: Request,
    db: AsyncSession = Depends(get_db),
    store: EphemeralStore = Depends(get_ephemeral_store),
    host_tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant),
):
    """
    Step 3 of the LTI 1.3 launch: validate the id_token, then
    - instructors and staff → the reading list editor (provisioning the course on first launch)
    - students and other roles → the public list page (no identity stored)
    """
    form = await request.form()
    id_token, state = form.get("id_token"), form.get("state")
    try:
        if not id_token or not state:
            raise lti.LaunchError("The LMS launch is incomplete. Try opening Stacks again.")
        record = await store.pop(f"lti:state:{state}")
        if record is None:
            raise lti.LaunchError("This launch has expired or was already used. Open Stacks again from your course.")
        platform = await db.get(LtiPlatform, uuid.UUID(record["platform_id"]))
        if platform is None or not platform.is_active:
            raise lti.LaunchError("This LMS is no longer registered with Stacks.")

        claims = await lti.validate_id_token(str(id_token), platform, record["nonce"])
        deployment = await lti.find_deployment(db, platform, claims)
        if (family := lti.product_family(claims)) and platform.product_family != family:
            platform.product_family = family
        organization_id = deployment.organization_id or platform.organization_id
        if _wrong_site(host_tenant, organization_id):
            raise lti.LaunchError(WRONG_SITE)

        lti.require_context(claims)  # before anything is created

        if lti.is_staff(claims):
            user = await lti.resolve_user(db, platform, organization_id, claims)
            offering = await lti.provision_offering(db, deployment, organization_id, claims)
            # Teaching this course in the LMS: may edit this offering's reading list
            await access.grant(db, user, access.INSTRUCTOR, ScopeType.course_offering, offering.id)
            reading_list = await lti.list_for_offering(db, offering, create_for=user)
            code = secrets.token_urlsafe(32)
            await store.put(
                f"lti:code:{code}",
                {"user_id": str(user.id), "next": f"/lists/{reading_list.id}"},
                LOGIN_CODE_TTL_SECONDS,
            )
            return RedirectResponse(f"/launch?code={code}", status_code=303)

        offering = await lti.find_offering(db, deployment, claims)
        if offering is None:
            raise lti.LaunchError(
                "The reading list for this course hasn't been set up yet. Your instructor needs to open Stacks first."
            )
        return RedirectResponse(await lti.public_path(db, offering), status_code=303)
    except lti.LaunchError as exc:
        # The error page is a normal response, so get_db would commit: undo partial work
        await db.rollback()
        logger.info("LTI launch refused: %s", exc)
        return _error_page(str(exc), tenant=host_tenant)


@router.get("/jwks", summary="Tool public JWKS endpoint")
async def lti_jwks(db: AsyncSession = Depends(get_db)):
    """The tool's public keys, one per registered platform, for LTI services and deep linking."""
    platforms = (await db.scalars(select(LtiPlatform).where(LtiPlatform.is_active.is_(True)))).all()
    keys = []
    for platform in platforms:
        jwk = RSAAlgorithm.to_jwk(load_pem_public_key(platform.tool_public_key.encode()), as_dict=True)
        keys.append({**jwk, "kid": platform.tool_key_id, "alg": "RS256", "use": "sig"})
    return {"keys": keys}



# Deep linking (LtiDeepLinkingRequest) is not implemented yet; such launches get a
# clear message from validate_id_token instead of a 404.
