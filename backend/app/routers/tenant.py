"""The organization this hostname serves: public details, page policy, theme and logo."""
import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import tenancy, theme

router = APIRouter()


class ThemeInfo(BaseModel):
    mode: str = "stacks"
    has_logo: bool = False
    version: str = ""


class TenantInfo(BaseModel):
    name: str | None = None
    slug: str | None = None
    theme: ThemeInfo = ThemeInfo()


async def _theme(db: AsyncSession, tenant: tenancy.Tenant | None) -> tuple[theme.ThemeSettings, dict | None, str | None]:
    """The organization's theme settings, logo, and (for 'match LMS: auto') its LMS."""
    if tenant is None:
        return theme.ThemeSettings(), None, None
    try:
        settings = theme.ThemeSettings.model_validate(tenant.settings.theme or {})
    except ValueError:
        settings = theme.ThemeSettings()  # never break pages over a bad stored theme
    detected = await tenancy.lms_family(db, tenant.organization_id) if settings.mode == "lms" else None
    return settings, tenant.settings.logo, detected


@router.get("", response_model=TenantInfo, summary="The organization this site serves")
async def tenant_info(tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant), db: AsyncSession = Depends(get_db)):
    """Public: the name, and theme details, for sign-in and student pages. Empty if none claims the host."""
    if tenant is None:
        return TenantInfo()
    settings, logo, detected = await _theme(db, tenant)
    return TenantInfo(
        name=tenant.name,
        slug=tenant.slug,
        theme=ThemeInfo(mode=settings.mode, has_logo=bool(logo), version=theme.version(settings, logo, detected)),
    )


def _cached(request: Request, etag: str, body: bytes | str, media_type: str) -> Response:
    """Short shared caching with revalidation: changes show within a minute."""
    headers = {"ETag": f'"{etag}"', "Cache-Control": "public, max-age=60"}
    if request.headers.get("if-none-match") == f'"{etag}"':
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=body, media_type=media_type, headers=headers)


@router.get("/theme.css", summary="This site's theme stylesheet")
async def theme_css(
    request: Request, tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant), db: AsyncSession = Depends(get_db)
):
    """Overrides for the standard Stacks theme (empty for the standard theme). Loaded by every page."""
    settings, logo, detected = await _theme(db, tenant)
    return _cached(request, theme.version(settings, logo, detected), theme.render_css(settings, detected), "text/css")


@router.get("/logo", summary="This site's logo")
async def logo(
    request: Request, tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant), db: AsyncSession = Depends(get_db)
):
    settings, stored, _ = await _theme(db, tenant)
    if not stored:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo")
    response = _cached(request, theme.version(settings, stored), base64.b64decode(stored["data"]), stored["content_type"])
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get(
    "/frame-policy",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Content-Security-Policy for this site's pages",
)
async def frame_policy(tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant)):
    """For the web server in front of the frontend (nginx auth_request): pages are
    static files, so it asks here for their policy on this hostname: which LMS
    origins may frame them, and that everything else comes from Stacks itself.
    (The path predates the rest of the policy; nginx configs use it.)"""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Content-Security-Policy": tenancy.page_policy(tenant), "Cache-Control": "no-store"},
    )
