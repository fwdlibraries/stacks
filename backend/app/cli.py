"""Admin command line.

    python -m app.cli create-user --org demo --email you@example.edu --name "Your Name" [--admin]
    python -m app.cli register-lti-platform --org demo --issuer https://lms.example.edu \
        --client-id ... --auth-login-url ... --auth-token-url ... --jwks-url ... \
        --deployment-id 1 [--deployment-id 2 ...]
    python -m app.cli configure-source --org demo --kind alma --region na
    python -m app.cli configure-source --org demo --kind primo --region na \
        --vid 01ABC_INST:MAIN --discovery-url https://abc.primo.exlibrisgroup.com [--tab ... --scope ...]
    python -m app.cli configure-source --org demo --kind libkey --library-id 1234
    python -m app.cli list-sources --org demo
    python -m app.cli sync-catalogue --org demo [--limit 1000]
    python -m app.cli configure-links --org demo --stack libkey,alma,open_access [--cache-hours 6] [--timeout 2.5]
    python -m app.cli lookup --org demo "10.1000/xyz 978-0-14-044913-6"
    python -m app.cli generate-credentials-key

Passwords and API keys are prompted for (or read from stdin with --password-stdin /
--api-key-stdin), never passed as arguments, so they don't end up in shell history
or `ps` output.
"""
import argparse
import asyncio
import getpass
import sys
import uuid
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import (
    IdentityProvider,
    LibrarySource,
    LtiDeployment,
    LtiPlatform,
    Organization,
    User,
    UserIdentity,
)
from app.services.auth_service import BCRYPT_MAX_BYTES, AuthService

MIN_PASSWORD_LENGTH = 12


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Confirm password: ") != password:
            sys.exit("Passwords do not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode()) > BCRYPT_MAX_BYTES:
        sys.exit(f"Password must be at most {BCRYPT_MAX_BYTES} bytes.")
    return password


async def create_user(args: argparse.Namespace) -> None:
    password = _read_password(args.password_stdin)
    async with AsyncSessionLocal() as db:
        org = await db.scalar(select(Organization).where(Organization.slug == args.org))
        if org is None:
            sys.exit(f"No organization with slug '{args.org}'.")

        email = args.email.strip().lower()
        if await db.scalar(select(User.id).where(func.lower(User.email) == email)):
            sys.exit(f"A user with email {email} already exists.")

        now = datetime.now(UTC)
        user = User(
            organization_id=org.id,
            email=email,
            display_name=args.name,
            is_system_admin=args.admin,
            password_hash=AuthService.hash_password(password),
            password_changed_at=now,
        )
        user.identities.append(
            UserIdentity(provider=IdentityProvider.local, provider_user_id=email, provider_email=email)
        )
        db.add(user)
        await db.commit()
        role = "system admin" if args.admin else "user"
        print(f"Created {role} {email} in '{org.name}'.")


def _generate_tool_keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_pem, public_pem


async def register_lti_platform(args: argparse.Namespace) -> None:
    """Register an LMS (issuer + client_id), or add deployments to an existing registration."""
    async with AsyncSessionLocal() as db:
        org = await db.scalar(select(Organization).where(Organization.slug == args.org))
        if org is None:
            sys.exit(f"No organization with slug '{args.org}'.")

        platform = await db.scalar(
            select(LtiPlatform).where(LtiPlatform.issuer == args.issuer, LtiPlatform.client_id == args.client_id)
        )
        if platform is None:
            missing = [f for f in ("auth_login_url", "auth_token_url", "jwks_url") if not getattr(args, f)]
            if missing:
                sys.exit("New registrations need " + ", ".join("--" + m.replace("_", "-") for m in missing) + ".")
            private_pem, public_pem = _generate_tool_keys()
            platform = LtiPlatform(
                organization_id=org.id,
                issuer=args.issuer,
                client_id=args.client_id,
                auth_login_url=args.auth_login_url,
                auth_token_url=args.auth_token_url,
                jwks_url=args.jwks_url,
                tool_private_key=private_pem,
                tool_public_key=public_pem,
                tool_key_id=uuid.uuid4().hex,
            )
            db.add(platform)
            await db.flush()
            print(f"Registered {args.issuer} (client_id {args.client_id}) for '{org.name}'.")
        else:
            print(f"{args.issuer} (client_id {args.client_id}) is already registered; adding deployments.")

        existing = set(
            (await db.scalars(select(LtiDeployment.deployment_id).where(LtiDeployment.platform_id == platform.id))).all()
        )
        for deployment_id in args.deployment_id:
            if deployment_id in existing:
                print(f"  deployment {deployment_id}: already registered")
            else:
                db.add(LtiDeployment(platform_id=platform.id, deployment_id=deployment_id, organization_id=org.id))
                print(f"  deployment {deployment_id}: added")
        await db.commit()

    base = settings.public_base_url.rstrip("/")
    print(
        "\nEnter these in the LMS tool registration:\n"
        f"  OIDC login initiation URL:  {base}/lti/login\n"
        f"  Redirect / launch URL:      {base}/lti/launch\n"
        f"  Target link URI:            {base}/lti/launch\n"
        f"  Public keyset (JWKS) URL:   {base}/lti/jwks\n"
        "  Custom parameter (optional): term=<your LMS's term or semester variable>"
    )


async def _get_org(db, slug: str) -> Organization:
    org = await db.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        sys.exit(f"No organization with slug '{slug}'.")
    return org


async def configure_source(args: argparse.Namespace) -> None:
    from pydantic import ValidationError

    from app.ingest.sources import SOURCE_CONFIGS
    from app.services import credentials

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        source = await db.scalar(
            select(LibrarySource).where(LibrarySource.organization_id == org.id, LibrarySource.kind == args.kind)
        )
        # Start from the stored settings so a re-run only needs the options that change
        config = dict(source.config) if source else {}
        options = {
            "library_id": args.library_id,
            "resolver_url": args.resolver_url,
            "region": args.region,
            "vid": args.vid,
            "tab": args.tab,
            "scope": args.scope,
            "discovery_url": args.discovery_url,
            "interface": args.interface,
        }
        config.update({k: v for k, v in options.items() if v is not None})
        try:
            validated = SOURCE_CONFIGS[args.kind].model_validate(config)
        except ValidationError as exc:
            sys.exit(f"Invalid {args.kind} settings:\n{exc}")

        if source is None or not args.keep_key:
            label = "LibKey API access token" if args.kind == "libkey" else f"{args.kind.capitalize()} API key"
            if args.api_key_stdin:
                api_key = sys.stdin.readline().strip()
            else:
                api_key = getpass.getpass(f"{label}: ").strip()
            if not api_key:
                sys.exit("An API key is required.")
        if source is None:
            source = LibrarySource(organization_id=org.id, kind=args.kind)
            db.add(source)
        source.config = validated.model_dump()
        if source.api_key_encrypted is None or not args.keep_key:
            source.api_key_encrypted = credentials.encrypt(api_key)
        source.is_active = not args.disable
        await db.commit()
    state = "disabled" if args.disable else "active"
    print(f"{args.kind} source for '{org.name}' saved ({state}): {validated.model_dump()}")


async def configure_links(args: argparse.Namespace) -> None:
    from pydantic import ValidationError

    from app.services.resolution import ResolutionConfig

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        current = dict(org.link_resolver_settings or {})
        if args.stack is not None:
            current["stack"] = [s.strip() for s in args.stack.split(",") if s.strip()]
        if args.cache_hours is not None:
            current["cache_ttl_seconds"] = int(args.cache_hours * 3600)
        if args.timeout is not None:
            current["step_timeout_seconds"] = args.timeout
        try:
            config = ResolutionConfig.model_validate(current)
        except ValidationError as exc:
            sys.exit(f"Invalid link settings:\n{exc}")
        org.link_resolver_settings = config.model_dump()
        await db.commit()
    stack = " → ".join(config.stack) or "(none: plain links)"
    print(
        f"Links for '{org.name}': {stack} → fallback; cache {config.cache_ttl_seconds / 3600:g} h; "
        f"step timeout {config.step_timeout_seconds:g} s"
    )


async def sync_catalogue(args: argparse.Namespace) -> None:
    import httpx

    from app.ingest.resolvers import ResolveContext
    from app.ingest.sources import load_sources
    from app.ingest.sync import sync_organization

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        sources = await load_sources(db, org.id)
        if "alma" not in sources:
            sys.exit(f"'{org.name}' has no active Alma source; see configure-source.")
        async with httpx.AsyncClient(timeout=30.0) as http:
            report = await sync_organization(db, org.id, ResolveContext(http=http, sources=sources), limit=args.limit)
        await db.commit()
    print(
        f"Checked {report.checked}: {report.updated} updated, {report.unchanged} unchanged, "
        f"{report.flagged} flagged, {report.restored} restored, {report.skipped} skipped"
    )
    for error in report.errors:
        print("Error:", error)


async def list_sources(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        rows = (await db.scalars(select(LibrarySource).where(LibrarySource.organization_id == org.id))).all()
    if not rows:
        print(f"No library sources configured for '{org.name}'.")
    for row in rows:
        key = "key set" if row.api_key_encrypted else "no key"
        print(f"{row.kind:6} {'active' if row.is_active else 'disabled':8} {key:7} {row.config}")


async def lookup(args: argparse.Namespace) -> None:
    import httpx

    from app.ingest import pipeline
    from app.ingest.resolvers import ResolveContext
    from app.ingest.sources import load_sources

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        sources = await load_sources(db, org.id)
    async with httpx.AsyncClient(timeout=15.0) as http:
        result = await pipeline.lookup(args.query, ResolveContext(http=http, sources=sources))
    print("Sources:", ", ".join(sources) or "none configured (open sources only)")
    print("Identifiers:", ", ".join(f"{i.kind}={i.value}" for i in result.identifiers) or "none found")
    for warning in result.warnings:
        print("Warning:", warning)
    for c in result.candidates:
        d = c.draft
        names = "; ".join(d.author or []) or "-"
        print(f"\n[{c.source_system} {c.source_identifier}] {c.match_method}, confidence {c.confidence:.2f}")
        print(f"  {d.title}\n  {names} ({d.year or 'n.d.'}) {d.resource_type}  isbn={d.isbn} doi={d.doi}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="Create a local (email + password) user")
    p.add_argument("--org", required=True, help="Organization slug, e.g. demo")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True, help="Display name")
    p.add_argument("--admin", action="store_true", help="Make the user a system administrator")
    p.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")

    p = sub.add_parser("register-lti-platform", help="Register an LMS for LTI 1.3 launches")
    p.add_argument("--org", required=True, help="Organization slug the LMS belongs to")
    p.add_argument("--issuer", required=True, help="Platform issuer (iss), e.g. https://canvas.instructure.com")
    p.add_argument("--client-id", required=True, help="Client ID the LMS assigned to Stacks")
    p.add_argument("--auth-login-url", help="Platform OIDC authorization endpoint")
    p.add_argument("--auth-token-url", help="Platform OAuth2 token endpoint")
    p.add_argument("--jwks-url", help="Platform public keyset URL")
    p.add_argument("--deployment-id", action="append", required=True, help="Deployment ID (repeatable)")

    p = sub.add_parser("configure-source", help="Connect an organization to Alma or Primo")
    p.add_argument("--org", required=True, help="Organization slug")
    p.add_argument("--kind", required=True, choices=["alma", "primo", "libkey"])
    p.add_argument("--region", choices=["na", "eu", "ap", "aps", "ca", "cn"], help="Ex Libris API region")
    p.add_argument("--vid", help="Primo view ID, e.g. 01ABC_INST:MAIN")
    p.add_argument("--tab", help="Primo search tab (default Everything)")
    p.add_argument("--scope", help="Primo search scope (default MyInst_and_CI)")
    p.add_argument("--discovery-url", help="Primo origin, e.g. https://abc.primo.exlibrisgroup.com")
    p.add_argument("--interface", choices=["nde", "ve"], help="Primo interface students use (default nde)")
    p.add_argument("--resolver-url", help="Alma origin for its link resolver (default: derived from Primo)")
    p.add_argument("--library-id", type=int, help="LibKey library ID")
    p.add_argument("--api-key-stdin", action="store_true", help="Read the API key from stdin")
    p.add_argument("--keep-key", action="store_true", help="Update settings but keep the stored API key")
    p.add_argument("--disable", action="store_true", help="Save but don't use this source")

    p = sub.add_parser("configure-links", help="Set the link resolver stack, cache and timeout")
    p.add_argument("--org", required=True)
    p.add_argument("--stack", help="Comma-separated, in order: libkey,alma,open_access ('' for plain links)")
    p.add_argument("--cache-hours", type=float, help="Reuse a resolved link for this long (default 6)")
    p.add_argument("--timeout", type=float, help="Seconds before a slow step is skipped (default 2.5)")

    p = sub.add_parser("sync-catalogue", help="Update citations bound to Alma records now")
    p.add_argument("--org", required=True)
    p.add_argument("--limit", type=int, default=1000, help="Citations to check, oldest-checked first")

    p = sub.add_parser("list-sources", help="Show an organization's library sources (never the keys)")
    p.add_argument("--org", required=True)

    p = sub.add_parser("lookup", help="Run a citation lookup as the organization would")
    p.add_argument("--org", required=True)
    p.add_argument("query", help="DOI, ISBN, MMS ID, or text containing them")

    sub.add_parser("generate-credentials-key", help="Print a new CREDENTIALS_KEY value")

    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(create_user(args))
    elif args.command == "register-lti-platform":
        asyncio.run(register_lti_platform(args))
    elif args.command == "configure-source":
        asyncio.run(configure_source(args))
    elif args.command == "configure-links":
        asyncio.run(configure_links(args))
    elif args.command == "sync-catalogue":
        asyncio.run(sync_catalogue(args))
    elif args.command == "list-sources":
        asyncio.run(list_sources(args))
    elif args.command == "lookup":
        asyncio.run(lookup(args))
    elif args.command == "generate-credentials-key":
        from app.services.credentials import generate_key
        print(generate_key())


if __name__ == "__main__":
    main()
