"""LTI 1.3 resource link launches: OIDC login, id_token validation, provisioning.

Validation follows the IMS Security Framework and LTI 1.3 core spec: the id_token
signature is checked against the platform's JWKS, then iss, aud/azp, exp/iat,
nonce, LTI version, message type and deployment are checked explicitly.
"""
import hashlib
import re
import uuid
from functools import lru_cache
from urllib.parse import quote, urlencode, urlsplit

import anyio
import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    College,
    CourseOffering,
    CourseTemplate,
    Department,
    LtiContextMapping,
    LtiDeployment,
    LtiPlatform,
    LtiUserMapping,
    OfferingListOverride,
    Organization,
    ReadingList,
    User,
)

LTI_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/"
CLAIM_MESSAGE_TYPE = LTI_CLAIM + "message_type"
CLAIM_VERSION = LTI_CLAIM + "version"
CLAIM_DEPLOYMENT_ID = LTI_CLAIM + "deployment_id"
CLAIM_CONTEXT = LTI_CLAIM + "context"
CLAIM_RESOURCE_LINK = LTI_CLAIM + "resource_link"
CLAIM_ROLES = LTI_CLAIM + "roles"
CLAIM_CUSTOM = LTI_CLAIM + "custom"
CLAIM_TOOL_PLATFORM = LTI_CLAIM + "tool_platform"

# tool_platform.product_family_code → the LMS look Stacks can match
PRODUCT_FAMILIES = {"desire2learn": "brightspace", "brightspace": "brightspace", "d2l": "brightspace",
                    "canvas": "canvas", "moodle": "moodle"}

RESOURCE_LINK_REQUEST = "LtiResourceLinkRequest"

# Roles that may edit reading lists. LTI 1.3 roles are URIs; match on the
# fragment so context (membership#…) and institution/system Administrator all count.
STAFF_ROLE_SUFFIXES = ("#Instructor", "#TeachingAssistant", "#ContentDeveloper", "#Administrator")

# Courses provisioned from the LMS go under this placeholder college/department
# until an administrator files them properly.
LTI_DEFAULT_EXTERNAL_ID = "lti-default"
LTI_DEFAULT_NAME = "Courses from the LMS"

DEFAULT_TERM = "current"


class LaunchError(Exception):
    """A launch that can't proceed. The message is shown to the user."""


# ── OIDC login initiation ────────────────────────────────────────────────────

async def find_platform(db: AsyncSession, issuer: str | None, client_id: str | None) -> LtiPlatform:
    if not issuer:
        raise LaunchError("The LMS did not identify itself (missing iss).")
    query = select(LtiPlatform).where(LtiPlatform.issuer == issuer, LtiPlatform.is_active.is_(True))
    if client_id:
        query = query.where(LtiPlatform.client_id == client_id)
    platforms = (await db.scalars(query)).all()
    if not platforms:
        raise LaunchError("This LMS is not registered with Stacks. Ask your Stacks administrator to register it.")
    if len(platforms) > 1:
        raise LaunchError("Several registrations match this LMS. It must send client_id with the login request.")
    return platforms[0]


def auth_request_url(platform: LtiPlatform, *, redirect_uri: str, login_hint: str,
                     lti_message_hint: str | None, state: str, nonce: str) -> str:
    params = {
        "scope": "openid",
        "response_type": "id_token",
        "response_mode": "form_post",
        "prompt": "none",
        "client_id": platform.client_id,
        "redirect_uri": redirect_uri,
        "login_hint": login_hint,
        "state": state,
        "nonce": nonce,
    }
    if lti_message_hint:
        params["lti_message_hint"] = lti_message_hint
    separator = "&" if "?" in platform.auth_login_url else "?"
    return f"{platform.auth_login_url}{separator}{urlencode(params)}"


# ── id_token validation ──────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    # PyJWKClient caches keys and refetches when it sees an unknown kid
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


async def _signing_key(jwks_url: str, id_token: str):
    # PyJWKClient fetches synchronously; keep it off the event loop
    return await anyio.to_thread.run_sync(_jwks_client(jwks_url).get_signing_key_from_jwt, id_token)


async def validate_id_token(id_token: str, platform: LtiPlatform, expected_nonce: str) -> dict:
    try:
        signing_key = await _signing_key(platform.jwks_url, id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=platform.client_id,
            issuer=platform.issuer,
            leeway=60,
            options={"require": ["iss", "aud", "exp", "iat", "sub", "nonce"]},
        )
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise LaunchError("The launch from the LMS could not be verified. Try opening Stacks again.") from exc

    # With several audiences, azp must name this tool (OIDC Core §3.1.3.7)
    aud = claims["aud"]
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != platform.client_id:
        raise LaunchError("The launch from the LMS was meant for a different tool.")
    if claims["nonce"] != expected_nonce:
        raise LaunchError("The launch from the LMS could not be verified. Try opening Stacks again.")
    if claims.get(CLAIM_VERSION) != "1.3.0":
        raise LaunchError("Stacks supports LTI 1.3 launches only.")
    if claims.get(CLAIM_MESSAGE_TYPE) != RESOURCE_LINK_REQUEST:
        raise LaunchError("This kind of LTI launch isn't supported yet. Add Stacks to the course as a link.")
    if not (claims.get(CLAIM_RESOURCE_LINK) or {}).get("id"):
        raise LaunchError("The launch from the LMS is missing its resource link.")
    return claims


async def find_deployment(db: AsyncSession, platform: LtiPlatform, claims: dict) -> LtiDeployment:
    deployment = await db.scalar(
        select(LtiDeployment).where(
            LtiDeployment.platform_id == platform.id,
            LtiDeployment.deployment_id == str(claims.get(CLAIM_DEPLOYMENT_ID, "")),
            LtiDeployment.is_active.is_(True),
        )
    )
    if deployment is None:
        raise LaunchError("This LMS deployment is not registered with Stacks. Ask your Stacks administrator.")
    return deployment


def is_staff(claims: dict) -> bool:
    return any(str(role).endswith(STAFF_ROLE_SUFFIXES) for role in claims.get(CLAIM_ROLES) or [])


def term_from(claims: dict) -> str:
    """URL-safe term slug from the `term` custom parameter, else 'current'."""
    raw = str((claims.get(CLAIM_CUSTOM) or {}).get("term") or "")
    # Unsubstituted LMS variables arrive literally, e.g. "$Canvas.term.name"
    if raw.startswith("$"):
        raw = ""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or DEFAULT_TERM


# ── Provisioning ─────────────────────────────────────────────────────────────

async def resolve_user(db: AsyncSession, platform: LtiPlatform, organization_id: uuid.UUID, claims: dict) -> User:
    """The Stacks user for this LMS user (by platform + sub), created on first launch."""
    sub = str(claims["sub"])
    mapping = await db.scalar(
        select(LtiUserMapping).where(LtiUserMapping.platform_id == platform.id, LtiUserMapping.lti_user_id == sub)
    )
    if mapping is not None:
        user = await db.get(User, mapping.user_id)
        mapping.last_seen_at = func.now()
    else:
        name = claims.get("name") or " ".join(
            part for part in (claims.get("given_name"), claims.get("family_name")) if part
        )
        email = claims.get("email")
        if not email:
            # Some LMS privacy settings withhold email; use a stable, non-deliverable placeholder
            host = urlsplit(platform.issuer).hostname or "lms"
            email = f"lti-{hashlib.sha256(sub.encode()).hexdigest()[:16]}@{host}.invalid"
        # Not linked to an existing local account by email: the LMS email isn't verified for us
        user = User(
            organization_id=organization_id,
            email=email.lower(),
            display_name=name or "LMS user",
            given_name=claims.get("given_name"),
            family_name=claims.get("family_name"),
        )
        db.add(user)
        await db.flush()
        db.add(LtiUserMapping(platform_id=platform.id, lti_user_id=sub, user_id=user.id, last_seen_at=func.now()))
    if user is None or not user.is_active:
        raise LaunchError("Your Stacks account is inactive. Contact your Stacks administrator.")
    return user


async def _default_department(db: AsyncSession, organization_id: uuid.UUID) -> Department:
    college = await db.scalar(
        select(College).where(
            College.organization_id == organization_id, College.external_id == LTI_DEFAULT_EXTERNAL_ID
        )
    )
    if college is None:
        college = College(organization_id=organization_id, name=LTI_DEFAULT_NAME, external_id=LTI_DEFAULT_EXTERNAL_ID)
        db.add(college)
        await db.flush()
    department = await db.scalar(
        select(Department).where(Department.college_id == college.id, Department.external_id == LTI_DEFAULT_EXTERNAL_ID)
    )
    if department is None:
        department = Department(college_id=college.id, name=LTI_DEFAULT_NAME, external_id=LTI_DEFAULT_EXTERNAL_ID)
        db.add(department)
        await db.flush()
    return department


def require_context(claims: dict) -> dict:
    context = claims.get(CLAIM_CONTEXT) or {}
    if not context.get("id"):
        raise LaunchError("Open Stacks from inside a course in your LMS.")
    return context


async def find_offering(db: AsyncSession, deployment: LtiDeployment, claims: dict) -> CourseOffering | None:
    """The offering already mapped to this LMS course, if any (no provisioning)."""
    mapping = await db.scalar(
        select(LtiContextMapping).where(
            LtiContextMapping.deployment_id == deployment.id,
            LtiContextMapping.lti_context_id == str(require_context(claims)["id"]),
        )
    )
    if mapping is None or mapping.course_offering_id is None:
        return None
    mapping.last_launched_at = func.now()
    return await db.get(CourseOffering, mapping.course_offering_id)


async def provision_offering(
    db: AsyncSession, deployment: LtiDeployment, organization_id: uuid.UUID, claims: dict
) -> CourseOffering:
    """Find or create the course, offering and context mapping for this LMS course."""
    offering = await find_offering(db, deployment, claims)
    if offering is not None:
        return offering

    context = require_context(claims)
    code = str(context.get("label") or context.get("title") or context["id"]).strip()
    title = str(context.get("title") or code).strip()
    term = term_from(claims)

    # Reuse a course with the same code in this organization (e.g. the next term)
    template = await db.scalar(
        select(CourseTemplate)
        .join(CourseTemplate.department)
        .join(Department.college)
        .where(College.organization_id == organization_id, func.lower(CourseTemplate.code) == code.lower())
        .limit(1)
    )
    if template is None:
        department = await _default_department(db, organization_id)
        template = CourseTemplate(department_id=department.id, code=code, name=title)
        db.add(template)
        await db.flush()

    offering = await db.scalar(
        select(CourseOffering).where(
            CourseOffering.course_template_id == template.id, CourseOffering.term == term
        ).limit(1)
    )
    if offering is None:
        offering = CourseOffering(
            course_template_id=template.id,
            term=term,
            lti_context_id=str(context["id"]),
            lti_deployment_id=deployment.deployment_id,
        )
        db.add(offering)
        await db.flush()

    db.add(
        LtiContextMapping(
            deployment_id=deployment.id,
            lti_context_id=str(context["id"]),
            lti_context_label=context.get("label"),
            lti_context_title=context.get("title"),
            course_offering_id=offering.id,
            last_launched_at=func.now(),
        )
    )
    await db.flush()
    return offering


async def list_for_offering(
    db: AsyncSession, offering: CourseOffering, *, create_for: User | None = None
) -> ReadingList | None:
    """
    The offering's reading list: an active override, else the course's list
    (published first, then most recent). Creates a draft list if `create_for` is given.
    """
    reading_list = await db.scalar(
        select(ReadingList)
        .join(OfferingListOverride, OfferingListOverride.reading_list_id == ReadingList.id)
        .where(OfferingListOverride.course_offering_id == offering.id, OfferingListOverride.is_active.is_(True))
        .limit(1)
    )
    if reading_list is None:
        reading_list = await db.scalar(
            select(ReadingList)
            .where(ReadingList.course_template_id == offering.course_template_id)
            .order_by(ReadingList.is_published.desc(), ReadingList.updated_at.desc())
            .limit(1)
        )
    if reading_list is None and create_for is not None:
        template = await db.get(CourseTemplate, offering.course_template_id)
        reading_list = ReadingList(
            course_template_id=template.id,
            title=f"{template.name} Reading List",
            visibility="public",
            is_published=False,
            created_by=create_for.id,
        )
        db.add(reading_list)
        await db.flush()
    return reading_list


async def public_path(db: AsyncSession, offering: CourseOffering) -> str:
    """Student URL for an offering: /public/{org}/{course}/{term}."""
    row = (
        await db.execute(
            select(Organization.slug, CourseTemplate.code)
            .select_from(CourseTemplate)
            .join(CourseTemplate.department)
            .join(Department.college)
            .join(College.organization)
            .where(CourseTemplate.id == offering.course_template_id)
        )
    ).one()
    return "/public/" + "/".join(quote(part, safe="") for part in (row.slug, row.code, offering.term))


def generate_tool_keys() -> tuple[str, str]:
    """A new RSA key pair for signing as the tool (PEM private, PEM public)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_pem, public_pem


def product_family(claims: dict) -> str | None:
    """Which LMS sent this launch, as Stacks names it (None if it doesn't say)."""
    code = str((claims.get(CLAIM_TOOL_PLATFORM) or {}).get("product_family_code") or "").strip().lower()
    return PRODUCT_FAMILIES.get(code, code or None)
