import uuid

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_system_admin: bool
    must_change_password: bool
    organization: OrganizationSummary
    # What the user may administer (from their roles), for showing admin screens
    can: "Capabilities"


class Capabilities(BaseModel):
    manage_settings: bool = False  # organization-wide only
    manage_people: bool = False  # anywhere (scoped)
    manage_courses: bool = False
    view_reports: bool = False


class LtiCodeExchange(BaseModel):
    code: str


class LtiExchangeResponse(TokenResponse):
    next: str  # editor path to open, e.g. /lists/{id}

CurrentUser.model_rebuild()
