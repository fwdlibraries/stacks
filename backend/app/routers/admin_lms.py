"""LMS (LTI 1.3) registrations: what the CLI's register-lti-platform does, for admins."""
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import require_permission
from app.models.models import LtiDeployment, LtiPlatform, LtiUserMapping, User
from app.services import tenancy
from app.services.lti_service import generate_tool_keys

router = APIRouter()
manage_settings = require_permission("settings.manage")

_URL = re.compile(r"^https://[^\s/]+(/\S*)?$")


class ToolUrls(BaseModel):
    """What to enter in the LMS when registering Stacks."""

    login_url: str
    redirect_url: str
    target_link_uri: str
    jwks_url: str


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    deployment_id: str
    label: str | None = None
    is_active: bool


class PlatformOut(BaseModel):
    id: uuid.UUID
    issuer: str
    client_id: str
    auth_login_url: str
    auth_token_url: str
    jwks_url: str
    is_active: bool
    created_at: datetime
    deployments: list[DeploymentOut]
    people: int  # people who have opened Stacks from this LMS


class LmsOut(BaseModel):
    tool: ToolUrls
    platforms: list[PlatformOut]


def _https(value: str) -> str:
    value = value.strip()
    if not _URL.match(value):
        raise ValueError("Enter an https:// address")
    return value


class PlatformIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=300)
    auth_login_url: str = Field(max_length=1000)
    auth_token_url: str = Field(max_length=1000)
    jwks_url: str = Field(max_length=1000)
    deployment_ids: list[str] = Field(default_factory=list, max_length=50)

    _urls = field_validator("issuer", "auth_login_url", "auth_token_url", "jwks_url")(_https)

    @field_validator("client_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class PlatformUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_login_url: str | None = Field(default=None, max_length=1000)
    auth_token_url: str | None = Field(default=None, max_length=1000)
    jwks_url: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None

    @field_validator("auth_login_url", "auth_token_url", "jwks_url")
    @classmethod
    def _urls(cls, value: str | None) -> str | None:
        return None if value is None else _https(value)


class DeploymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deployment_id: str = Field(min_length=1, max_length=300)
    label: str | None = Field(default=None, max_length=200)


async def _lms_out(db: AsyncSession, user: User) -> LmsOut:
    base = tenancy.base_url(await tenancy.tenant_for_org(db, user.organization_id))
    platforms = (
        await db.scalars(
            select(LtiPlatform)
            .where(LtiPlatform.organization_id == user.organization_id)
            .options(selectinload(LtiPlatform.deployments))
            .order_by(LtiPlatform.created_at)
        )
    ).all()
    counts = dict(
        (
            await db.execute(
                select(LtiUserMapping.platform_id, func.count())
                .where(LtiUserMapping.platform_id.in_([p.id for p in platforms]))
                .group_by(LtiUserMapping.platform_id)
            )
        ).all()
    ) if platforms else {}
    return LmsOut(
        tool=ToolUrls(
            login_url=f"{base}/lti/login",
            redirect_url=f"{base}/lti/launch",
            target_link_uri=f"{base}/lti/launch",
            jwks_url=f"{base}/lti/jwks",
        ),
        platforms=[
            PlatformOut(
                id=p.id, issuer=p.issuer, client_id=p.client_id, auth_login_url=p.auth_login_url,
                auth_token_url=p.auth_token_url, jwks_url=p.jwks_url, is_active=bool(p.is_active),
                created_at=p.created_at,
                deployments=[DeploymentOut.model_validate(d) for d in sorted(p.deployments, key=lambda d: d.created_at)],
                people=counts.get(p.id, 0),
            )
            for p in platforms
        ],
    )


async def _platform(db: AsyncSession, user: User, platform_id: uuid.UUID) -> LtiPlatform:
    platform = await db.get(LtiPlatform, platform_id)
    if platform is None or platform.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LMS not found")
    return platform


@router.get("/lms", response_model=LmsOut, summary="LMS registrations and the tool's URLs")
async def list_lms(user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    return await _lms_out(db, user)


@router.post("/lms", response_model=LmsOut, status_code=status.HTTP_201_CREATED, summary="Register an LMS")
async def register_lms(body: PlatformIn, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)):
    """Use the values the LMS shows after registering Stacks there (issuer, client ID,
    its OIDC, token and keyset URLs, deployment IDs). Stacks makes its own signing key."""
    taken = await db.scalar(
        select(LtiPlatform).where(LtiPlatform.issuer == body.issuer, LtiPlatform.client_id == body.client_id)
    )
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "That LMS registration (issuer and client ID) already exists")
    private_pem, public_pem = generate_tool_keys()
    platform = LtiPlatform(
        organization_id=user.organization_id, issuer=body.issuer, client_id=body.client_id,
        auth_login_url=body.auth_login_url, auth_token_url=body.auth_token_url, jwks_url=body.jwks_url,
        tool_private_key=private_pem, tool_public_key=public_pem, tool_key_id=uuid.uuid4().hex,
    )
    db.add(platform)
    await db.flush()
    for deployment_id in dict.fromkeys(d.strip() for d in body.deployment_ids if d.strip()):
        db.add(LtiDeployment(platform_id=platform.id, deployment_id=deployment_id, organization_id=user.organization_id))
    await db.flush()
    return await _lms_out(db, user)


@router.patch("/lms/{platform_id}", response_model=LmsOut, summary="Change an LMS registration")
async def update_lms(
    platform_id: uuid.UUID, body: PlatformUpdate, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)
):
    """Issuer and client ID identify the registration and can't change: register again instead.
    Turning a registration off stops launches from it; nothing is deleted."""
    platform = await _platform(db, user, platform_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(platform, field, value)
    await db.flush()
    return await _lms_out(db, user)


@router.post("/lms/{platform_id}/deployments", response_model=LmsOut, status_code=status.HTTP_201_CREATED,
             summary="Add a deployment")
async def add_deployment(
    platform_id: uuid.UUID, body: DeploymentIn, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)
):
    platform = await _platform(db, user, platform_id)
    existing = await db.scalar(
        select(LtiDeployment).where(LtiDeployment.platform_id == platform.id, LtiDeployment.deployment_id == body.deployment_id.strip())
    )
    if existing:
        if existing.is_active:
            raise HTTPException(status.HTTP_409_CONFLICT, "That deployment is already registered")
        existing.is_active = True
    else:
        db.add(LtiDeployment(platform_id=platform.id, deployment_id=body.deployment_id.strip(),
                             label=body.label, organization_id=user.organization_id))
    await db.flush()
    return await _lms_out(db, user)


@router.delete("/lms/{platform_id}/deployments/{deployment_id}", response_model=LmsOut, summary="Turn off a deployment")
async def remove_deployment(
    platform_id: uuid.UUID, deployment_id: uuid.UUID, user: User = Depends(manage_settings), db: AsyncSession = Depends(get_db)
):
    """Launches from it stop. Kept (inactive) because courses provisioned from it refer to it."""
    platform = await _platform(db, user, platform_id)
    deployment = await db.get(LtiDeployment, deployment_id)
    if deployment is None or deployment.platform_id != platform.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    deployment.is_active = False
    await db.flush()
    return await _lms_out(db, user)
