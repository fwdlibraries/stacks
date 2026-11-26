"""Single sign-on with OpenID Connect (one protocol; SAML stays outside Stacks).

Flow: Authorization Code with PKCE. State, nonce and the PKCE verifier are kept
server-side (Redis, single use, 10 minutes). The ID token is validated strictly:
signature against the provider's published keys (RS256/ES256 only), issuer,
audience, expiry and nonce; for Microsoft Entra also the tenant (tid), so a
"common" endpoint can't let other tenants in.

Accounts are found by the provider's stable identifier (Entra: tenant + object
ID; others: issuer + sub), never by email. Email matters only to link an account
an administrator invited, and only when the provider vouches for it (verified,
or an Entra tenant domain) and its domain is allowed. Roles come from Stacks, or
from the provider's role claims through an explicit mapping, kept in step at
each sign-in.
"""
import base64
import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import (
    IdentityProvider,
    Role,
    ScopeType,
    SsoConfig,
    User,
    UserIdentity,
    UserRoleAssignment,
)
from app.services import access, credentials

STATE_TTL_SECONDS = 600
ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256"]
CALLBACK_PATH = "/api/v1/auth/oidc/callback"
_DISCOVERY_TTL = 600


class SsoError(Exception):
    """Sign-in can't continue; the message is shown to the person."""


@dataclass
class Discovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    fetched_at: float


_discovery_cache: dict[str, Discovery] = {}
_jwks_cache: dict[str, tuple[float, dict]] = {}


def valid_issuer(issuer: str) -> bool:
    """https only; plain http just with OIDC_ALLOW_HTTP (local testing with a mock provider)."""
    parts = urlsplit(issuer)
    if parts.scheme == "https" and parts.hostname:
        return True
    return parts.scheme == "http" and bool(parts.hostname) and settings.oidc_allow_http


async def discover(http: httpx.AsyncClient, issuer: str, *, fresh: bool = False) -> Discovery:
    issuer = issuer.rstrip("/")
    cached = _discovery_cache.get(issuer)
    if cached and not fresh and time.monotonic() - cached.fetched_at < _DISCOVERY_TTL:
        return cached
    try:
        resp = await http.get(f"{issuer}/.well-known/openid-configuration")
        resp.raise_for_status()
        doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SsoError("Your institution's sign-in service can't be reached right now.") from exc
    # The document must describe the issuer it was fetched from (OIDC Discovery §4.3)
    if str(doc.get("issuer", "")).rstrip("/") != issuer:
        raise SsoError("The sign-in service's configuration doesn't match its address.")
    try:
        found = Discovery(
            issuer=doc["issuer"],
            authorization_endpoint=doc["authorization_endpoint"],
            token_endpoint=doc["token_endpoint"],
            jwks_uri=doc["jwks_uri"],
            fetched_at=time.monotonic(),
        )
    except KeyError as exc:
        raise SsoError("The sign-in service's configuration is incomplete.") from exc
    for url in (found.authorization_endpoint, found.token_endpoint, found.jwks_uri):
        if not valid_issuer(url):
            raise SsoError("The sign-in service must use https.")
    _discovery_cache[issuer] = found
    return found


async def _signing_key(http: httpx.AsyncClient, jwks_uri: str, kid: str | None) -> jwt.PyJWK:
    async def load(fresh: bool) -> dict:
        cached = _jwks_cache.get(jwks_uri)
        if cached and not fresh and time.monotonic() - cached[0] < _DISCOVERY_TTL:
            return cached[1]
        resp = await http.get(jwks_uri)
        resp.raise_for_status()
        keys = resp.json()
        _jwks_cache[jwks_uri] = (time.monotonic(), keys)
        return keys

    for fresh in (False, True):  # keys rotate: refetch once for an unknown kid
        try:
            keyset = jwt.PyJWKSet.from_dict(await load(fresh))
        except (httpx.HTTPError, ValueError, jwt.PyJWKSetError) as exc:
            raise SsoError("Your institution's sign-in keys can't be read.") from exc
        for key in keyset.keys:
            if kid is None or key.key_id == kid:
                return key
    raise SsoError("The sign-in token was signed with an unknown key.")


def redirect_uri(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{CALLBACK_PATH}"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def start(http: httpx.AsyncClient, config: SsoConfig, base_url: str, next_path: str, store) -> str:
    """Where to send the browser to sign in. Records state for the callback."""
    found = await discover(http, config.issuer)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = _pkce()
    await store.put(
        f"oidc:state:{state}",
        {"org": str(config.organization_id), "nonce": nonce, "verifier": verifier, "next": next_path},
        STATE_TTL_SECONDS,
    )
    query = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri(base_url),
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{found.authorization_endpoint}?{urlencode(query)}"


def _entra_tenant(issuer: str) -> str | None:
    """The tenant ID in an Entra issuer (https://login.microsoftonline.com/<tid>/v2.0)."""
    parts = urlsplit(issuer)
    if parts.hostname in ("login.microsoftonline.com", "sts.windows.net"):
        segment = parts.path.strip("/").split("/")[0]
        try:
            return str(uuid.UUID(segment))
        except ValueError:
            return None  # "common" / "organizations": refused when saving the settings
    return None


def is_entra_multitenant(issuer: str) -> bool:
    parts = urlsplit(issuer)
    return parts.hostname in ("login.microsoftonline.com", "sts.windows.net") and _entra_tenant(issuer) is None


async def finish(http: httpx.AsyncClient, config: SsoConfig, base_url: str, code: str, record: dict) -> dict:
    """Exchange the code and validate the ID token; returns its claims."""
    found = await discover(http, config.issuer)
    try:
        secret = credentials.decrypt(config.client_secret_encrypted)
    except credentials.CredentialError as exc:
        raise SsoError("Single sign-on isn't set up correctly (the stored secret can't be read).") from exc
    try:
        resp = await http.post(
            found.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(base_url),
                "client_id": config.client_id,
                "client_secret": secret,
                "code_verifier": record["verifier"],
            },
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise SsoError("Your institution's sign-in service can't be reached right now.") from exc
    if resp.status_code != 200:
        raise SsoError("Your institution's sign-in service didn't accept the sign-in. Try again.")
    id_token = (resp.json() or {}).get("id_token")
    if not id_token:
        raise SsoError("Your institution's sign-in service didn't return an identity.")

    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise SsoError("The sign-in token is malformed.") from exc
    if header.get("alg") not in ALLOWED_ALGORITHMS:
        raise SsoError("The sign-in token uses an algorithm Stacks doesn't accept.")
    key = await _signing_key(http, found.jwks_uri, header.get("kid"))
    try:
        claims = jwt.decode(
            id_token,
            key=key.key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=config.client_id,
            issuer=found.issuer,
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise SsoError("The sign-in token couldn't be verified.") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), record["nonce"]):
        raise SsoError("The sign-in token doesn't belong to this sign-in. Try again.")
    expected_tid = _entra_tenant(found.issuer)
    if expected_tid and str(claims.get("tid", "")).lower() != expected_tid:
        raise SsoError("That account belongs to a different organization.")
    if config.require_mfa and "mfa" not in (claims.get("amr") or []):
        raise SsoError("Your institution requires multi-factor authentication for Stacks. Sign in again with it.")
    return claims


def identity_key(claims: dict) -> str:
    """A stable identifier for the person: never the email, which can change hands."""
    if claims.get("tid") and claims.get("oid"):
        return f"entra:{claims['tid']}:{claims['oid']}"
    return f"{claims['iss']}|{claims['sub']}"


def vouched_email(claims: dict) -> str | None:
    """An email the provider vouches for, or None."""
    email = str(claims.get("email") or "").strip().lower()
    if email and (claims.get("email_verified") is True or claims.get("xms_edov") in (True, "1", 1)):
        return email
    if claims.get("tid"):
        # Entra sign-in names (UPN) are in domains the tenant has verified
        upn = str(claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
        if "@" in upn:
            return upn
    return None


def _domain_allowed(email: str | None, domains: list[str]) -> bool:
    return bool(email) and email.rsplit("@", 1)[-1] in {d.lower().lstrip("@") for d in domains}


async def resolve_user(db: AsyncSession, config: SsoConfig, claims: dict) -> User:
    key = identity_key(claims)
    identity = await db.scalar(
        select(UserIdentity).where(UserIdentity.provider == IdentityProvider.oidc, UserIdentity.provider_user_id == key)
    )
    email = vouched_email(claims)
    name = str(claims.get("name") or "").strip() or (email or "Stacks user")

    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None or user.organization_id != config.organization_id:
            raise SsoError("That account isn't part of this organization's Stacks.")
        identity.last_used_at = datetime.now(UTC)
    else:
        user = None
        if _domain_allowed(email, config.allowed_domains):
            # An invitation for this person (and not yet linked to any sign-in)
            user = await db.scalar(
                select(User).where(
                    User.organization_id == config.organization_id,
                    func.lower(User.email) == email,
                    User.invited_at.is_not(None),
                    ~User.identities.any(UserIdentity.provider == IdentityProvider.oidc),
                )
            )
            if user is None and config.allow_signup:
                user = User(organization_id=config.organization_id, email=email, display_name=name)
                db.add(user)
                await db.flush()
        if user is None:
            raise SsoError(
                "There's no Stacks account for you yet. Ask your library to invite you."
                if config.allow_signup is False
                else "Your account's email domain isn't allowed to sign in to Stacks here."
            )
        db.add(
            UserIdentity(
                user_id=user.id, provider=IdentityProvider.oidc, provider_user_id=key, provider_email=email,
                provider_metadata={"issuer": claims.get("iss")}, last_used_at=datetime.now(UTC),
            )
        )
    if not user.is_active:
        raise SsoError("Your Stacks account is turned off. Contact your library.")
    if name and user.display_name in ("", "Stacks user", user.email):
        user.display_name = name
    await sync_roles(db, user, config, claims)
    user.last_login_at = datetime.now(UTC)
    await db.flush()
    return user


async def sync_roles(db: AsyncSession, user: User, config: SsoConfig, claims: dict) -> None:
    """Organization-wide roles from the provider's role claims: granted while present,
    removed when gone. Roles granted in Stacks are never touched."""
    if not config.role_mapping:
        return
    claimed = {str(r) for r in (claims.get("roles") or [])}
    wanted = {role for value, role in config.role_mapping.items() if value in claimed and role in access.SYSTEM_ROLES}
    roles = await access.ensure_catalog(db)
    current = {
        name: assignment
        for assignment, name in await db.execute(
            select(UserRoleAssignment, Role.name)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(
                and_(
                    UserRoleAssignment.user_id == user.id,
                    UserRoleAssignment.source == "sso",
                    UserRoleAssignment.scope_type == ScopeType.organization,
                )
            )
        )
    }
    for name, assignment in current.items():
        if name not in wanted:
            await db.delete(assignment)
    for name in wanted - set(current):
        existing = await db.scalar(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.role_id == roles[name].id,
                UserRoleAssignment.scope_type == ScopeType.organization,
                UserRoleAssignment.scope_id == config.organization_id,
            )
        )
        if existing is None:  # already granted by hand: leave it as it is
            db.add(UserRoleAssignment(
                user_id=user.id, role_id=roles[name].id, scope_type=ScopeType.organization,
                scope_id=config.organization_id, source="sso",
            ))
    await db.flush()
