"""The organization this hostname serves: public details, page policy, theme and logo."""
import base64

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

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


def _theme(tenant: tenancy.Tenant | None) -> tuple[theme.ThemeSettings, dict | None]:
    if tenant is None:
        return theme.ThemeSettings(), None
    try:
        settings = theme.ThemeSettings.model_validate(tenant.settings.theme or {})
    except ValueError:
        settings = theme.ThemeSettings()  # never break pages over a bad stored theme
    return settings, tenant.settings.logo


@router.get("", response_model=TenantInfo, summary="The organization this site serves")
async def tenant_info(tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant)):
    """Public: the name, and theme details, for sign-in and student pages. Empty if none claims the host."""
    if tenant is None:
        return TenantInfo()
    settings, logo = _theme(tenant)
    return TenantInfo(
        name=tenant.name,
        slug=tenant.slug,
        theme=ThemeInfo(mode=settings.mode, has_logo=bool(logo), version=theme.version(settings, logo)),
    )


def _cached(request: Request, etag: str, body: bytes | str, media_type: str) -> Response:
    """Short shared caching with revalidation: changes show within a minute."""
    headers = {"ETag": f'"{etag}"', "Cache-Control": "public, max-age=60"}
    if request.headers.get("if-none-match") == f'"{etag}"':
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=body, media_type=media_type, headers=headers)


@router.get("/theme.css", summary="This site's theme stylesheet")
async def theme_css(request: Request, tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant)):
    """Overrides for the standard Stacks theme (empty for the standard theme). Loaded by every page."""
    settings, logo = _theme(tenant)
    return _cached(request, theme.version(settings, logo), theme.render_css(settings), "text/css")


@router.get("/logo", summary="This site's logo")
async def logo(request: Request, tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant)):
    settings, stored = _theme(tenant)
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
