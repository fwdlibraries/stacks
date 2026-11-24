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

from app.config import settings
from app.database import get_db
from app.models.models import LtiPlatform
from app.services import lti_service as lti
from app.services.ephemeral import EphemeralStore, get_ephemeral_store

logger = logging.getLogger(__name__)
router = APIRouter()

STATE_TTL_SECONDS = 300
LOGIN_CODE_TTL_SECONDS = 60


def launch_url() -> str:
    return f"{settings.public_base_url.rstrip('/')}/lti/launch"


def _error_page(message: str, status_code: int = 400) -> HTMLResponse:
    """Plain page shown inside the LMS frame when a launch can't proceed."""
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Stacks</title>
<style>
  body {{ font-family: "Libre Baskerville", Georgia, serif; background: #F7F4EF; color: #2C3E5A;
         margin: 0; padding: 3rem 1.5rem; line-height: 1.7; }}
  main {{ max-width: 32rem; margin: 0 auto; }}
  h1 {{ font-family: "Playfair Display", Georgia, serif; font-weight: 600; font-size: 1.5625rem; }}
</style></head>
<body><main><h1>Stacks couldn't open</h1><p>{html.escape(message)}</p></main></body></html>"""
    return HTMLResponse(body, status_code=status_code)


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
    except lti.LaunchError as exc:
        return _error_page(str(exc))

    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    await store.put(f"lti:state:{state}", {"nonce": nonce, "platform_id": str(platform.id)}, STATE_TTL_SECONDS)
    url = lti.auth_request_url(
        platform,
        redirect_uri=launch_url(),
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
        organization_id = deployment.organization_id or platform.organization_id

        lti.require_context(claims)  # before anything is created

        if lti.is_staff(claims):
            user = await lti.resolve_user(db, platform, organization_id, claims)
            offering = await lti.provision_offering(db, deployment, organization_id, claims)
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
        return _error_page(str(exc))


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
