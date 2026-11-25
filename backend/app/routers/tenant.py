"""The organization this hostname serves: public details, and its frame policy."""
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.services import tenancy

router = APIRouter()


class TenantInfo(BaseModel):
    name: str | None = None
    slug: str | None = None


@router.get("", response_model=TenantInfo, summary="The organization this site serves")
async def tenant_info(tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant)):
    """Public: the name to show on sign-in and student pages. Empty if none claims the host."""
    return TenantInfo(name=tenant.name, slug=tenant.slug) if tenant else TenantInfo()


@router.get(
    "/frame-policy",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Content-Security-Policy frame-ancestors for this site",
)
async def frame_policy(tenant: tenancy.Tenant | None = Depends(tenancy.get_tenant)):
    """For the web server in front of the frontend (nginx auth_request): pages are
    static files, so it asks here which LMS origins may frame them on this hostname."""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Content-Security-Policy": tenancy.frame_policy(tenant), "Cache-Control": "no-store"},
    )
