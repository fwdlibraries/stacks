"""Admin command line.

    python -m app.cli create-user --org demo --email you@example.edu --name "Your Name" [--role Administrator]
    python -m app.cli grant-role --org demo --email you@example.edu --role Librarian [--college ARTS | --department HIST | --course HIST101]
    python -m app.cli revoke-role --org demo --email you@example.edu --role Librarian [--college … | --department … | --course …]
    python -m app.cli roles --org demo [--email you@example.edu]
    python -m app.cli register-lti-platform --org demo --issuer https://lms.example.edu \
        --client-id ... --auth-login-url ... --auth-token-url ... --jwks-url ... \
        --deployment-id 1 [--deployment-id 2 ...]
    python -m app.cli configure-source --org demo --kind alma --region na
    python -m app.cli configure-source --org demo --kind primo --region na \
        --vid 01ABC_INST:MAIN --discovery-url https://abc.primo.exlibrisgroup.com [--tab ... --scope ...]
    python -m app.cli configure-source --org demo --kind libkey --library-id 1234
    python -m app.cli list-sources --org demo
    python -m app.cli configure-org --org demo --add-domain stacks.example.edu --primary stacks.example.edu \
        --lms-origin https://lms.example.edu [--contact-email library@example.edu]
    python -m app.cli show-org --org demo
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

from sqlalchemy import func, or_, select

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
from app.services.lti_service import generate_tool_keys

MIN_PASSWORD_LENGTH = 12
ROLE_CHOICES = ["Administrator", "Librarian", "Instructor", "Viewer"]


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
        await db.flush()
        if args.role:
            from app.models.models import ScopeType
            from app.services import access
            await access.grant(db, user, args.role, ScopeType.organization, org.id)
        await db.commit()
        kind = "system admin" if args.admin else "user"
        role = f" with role {args.role} for the whole organization" if args.role else " (no roles yet: see grant-role)"
        print(f"Created {kind} {email} in '{org.name}'{role}.")


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
            private_pem, public_pem = generate_tool_keys()
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

    from app.services.tenancy import tenant_for_org

    async with AsyncSessionLocal() as db:
        base = (await tenant_for_org(db, org.id)).base_url
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


async def _scope(db, org: Organization, args: argparse.Namespace):
    """(scope_type, scope_id, label) from --college / --department / --course, else the organization."""
    from app.models.models import College, CourseTemplate, Department, ScopeType

    def matches(model, value):
        return or_(func.lower(model.code) == value.lower(), func.lower(model.name) == value.lower())

    if args.college:
        found = await db.scalar(select(College).where(College.organization_id == org.id, matches(College, args.college)))
        kind = ScopeType.college
    elif args.department:
        found = await db.scalar(
            select(Department).join(Department.college)
            .where(College.organization_id == org.id, matches(Department, args.department))
        )
        kind = ScopeType.department
    elif args.course:
        found = await db.scalar(
            select(CourseTemplate).join(CourseTemplate.department).join(Department.college)
            .where(College.organization_id == org.id, matches(CourseTemplate, args.course))
        )
        kind = ScopeType.course_template
    else:
        return ScopeType.organization, org.id, f"all of {org.name}"
    if found is None:
        sys.exit(f"No {kind.value.replace('_', ' ')} '{args.college or args.department or args.course}' in {org.name}.")
    return kind, found.id, f"{kind.value.replace('_template', '').replace('_', ' ')} {found.name}"


async def _user(db, org: Organization, email: str) -> User:
    user = await db.scalar(
        select(User).where(User.organization_id == org.id, func.lower(User.email) == email.strip().lower())
    )
    if user is None:
        sys.exit(f"No user {email} in {org.name}.")
    return user


async def grant_role(args: argparse.Namespace) -> None:
    from app.services import access

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        user = await _user(db, org, args.email)
        scope_type, scope_id, label = await _scope(db, org, args)
        await access.grant(db, user, args.role, scope_type, scope_id)
        await db.commit()
    print(f"{user.email} is now {args.role} for {label}.")


async def revoke_role(args: argparse.Namespace) -> None:
    from app.models.models import Role, UserRoleAssignment

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        user = await _user(db, org, args.email)
        scope_type, scope_id, label = await _scope(db, org, args)
        assignment = await db.scalar(
            select(UserRoleAssignment).join(Role, Role.id == UserRoleAssignment.role_id).where(
                UserRoleAssignment.user_id == user.id, Role.name == args.role,
                UserRoleAssignment.scope_type == scope_type, UserRoleAssignment.scope_id == scope_id,
            )
        )
        if assignment is None:
            sys.exit(f"{user.email} isn't {args.role} for {label}.")
        await db.delete(assignment)
        await db.commit()
    print(f"{user.email} is no longer {args.role} for {label}.")


async def list_roles(args: argparse.Namespace) -> None:
    from app.models.models import (
        College,
        CourseOffering,
        CourseTemplate,
        Department,
        Role,
        ScopeType,
        UserRoleAssignment,
    )

    names = {ScopeType.college: College, ScopeType.department: Department, ScopeType.course_template: CourseTemplate}
    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        query = (
            select(User, Role.name, UserRoleAssignment.scope_type, UserRoleAssignment.scope_id)
            .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(User.organization_id == org.id)
            .order_by(User.email, Role.name)
        )
        if args.email:
            query = query.where(func.lower(User.email) == args.email.strip().lower())
        rows = (await db.execute(query)).all()
        if not rows:
            print("No role assignments.")
        for user, role, scope_type, scope_id in rows:
            if scope_type == ScopeType.organization:
                where = "whole organization"
            elif scope_type == ScopeType.course_offering:
                offering = await db.get(CourseOffering, scope_id)
                template = offering and await db.get(CourseTemplate, offering.course_template_id)
                where = f"offering {template.code if template else '?'} {offering.term if offering else scope_id}"
            else:
                thing = await db.get(names[scope_type], scope_id)
                where = f"{scope_type.value.replace('_template', '').replace('_', ' ')} {thing.name if thing else scope_id}"
            print(f"{user.email or user.display_name:40} {role:14} {where}")


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

    from app.ingest.sources import context_for, load_sources
    from app.ingest.sync import sync_organization

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        sources = await load_sources(db, org.id)
        if "alma" not in sources:
            sys.exit(f"'{org.name}' has no active Alma source; see configure-source.")
        async with httpx.AsyncClient(timeout=30.0) as http:
            report = await sync_organization(db, org.id, await context_for(db, org.id, http), limit=args.limit)
        await db.commit()
    print(
        f"Checked {report.checked}: {report.updated} updated, {report.unchanged} unchanged, "
        f"{report.flagged} flagged, {report.restored} restored, {report.skipped} skipped"
    )
    for error in report.errors:
        print("Error:", error)


async def configure_org(args: argparse.Namespace) -> None:
    from pydantic import ValidationError

    from app.models.models import OrganizationDomain
    from app.services.tenancy import OrgSettings, normalize_host, tenant_for_org

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        for raw in args.add_domain or []:
            host = normalize_host(raw)
            if not host:
                sys.exit(f"'{raw}' isn't a hostname (e.g. stacks.library.example.edu).")
            taken = await db.scalar(select(OrganizationDomain).where(OrganizationDomain.hostname == host))
            if taken and taken.organization_id != org.id:
                sys.exit(f"{host} already belongs to another organization.")
            if not taken:
                db.add(OrganizationDomain(organization_id=org.id, hostname=host))
                await db.flush()
        if args.primary:
            host = normalize_host(args.primary)
            domains = list(await db.scalars(select(OrganizationDomain).where(OrganizationDomain.organization_id == org.id)))
            if host not in {d.hostname for d in domains}:
                sys.exit(f"{args.primary} isn't one of {org.name}'s domains; add it with --add-domain first.")
            for domain in domains:
                domain.is_primary = domain.hostname == host
        for raw in args.remove_domain or []:
            domain = await db.scalar(
                select(OrganizationDomain).where(
                    OrganizationDomain.organization_id == org.id, OrganizationDomain.hostname == normalize_host(raw)
                )
            )
            if domain:
                await db.delete(domain)

        current = dict(org.settings or {})
        if args.lms_origin is not None:
            current["frame_ancestors"] = [o for o in args.lms_origin if o] or []
        if args.clear_lms_origins:
            current.pop("frame_ancestors", None)
        if args.contact_email is not None:
            current["metadata_contact_email"] = args.contact_email or None
        try:
            org.settings = OrgSettings.model_validate(current).model_dump(exclude_none=True)
        except ValidationError as exc:
            sys.exit(f"Invalid settings:\n{exc}")
        await db.commit()
        await show_org_details(db, org, tenant_for_org)


async def show_org_details(db, org: Organization, tenant_for_org) -> None:
    from app.models.models import OrganizationDomain

    tenant = await tenant_for_org(db, org.id)
    domains = list(await db.scalars(
        select(OrganizationDomain).where(OrganizationDomain.organization_id == org.id).order_by(OrganizationDomain.hostname)
    ))
    print(f"{org.name} ({org.slug})")
    print("  Domains:      " + (", ".join(d.hostname + (" (primary)" if d.is_primary else "") for d in domains) or "none"))
    print(f"  Address:      {tenant.base_url}" + ("" if tenant.primary_host else "  (PUBLIC_BASE_URL: no domain yet)"))
    own = tenant.settings.frame_ancestors is not None
    print("  LMS origins:  " + (" ".join(tenant.frame_ancestors) or "none") + ("" if own else "  (FRAME_ANCESTORS default)"))
    print(f"  Contact:      {tenant.contact_email or 'none'}"
          + ("" if tenant.settings.metadata_contact_email else "  (METADATA_CONTACT_EMAIL default)"))


async def show_org(args: argparse.Namespace) -> None:
    from app.services.tenancy import tenant_for_org

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        await show_org_details(db, org, tenant_for_org)


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
    from app.ingest.sources import context_for, load_sources

    async with AsyncSessionLocal() as db:
        org = await _get_org(db, args.org)
        sources = await load_sources(db, org.id)
    async with httpx.AsyncClient(timeout=15.0) as http:
        async with AsyncSessionLocal() as db:
            ctx = await context_for(db, org.id, http)
        result = await pipeline.lookup(args.query, ctx)
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
    p.add_argument("--admin", action="store_true",
                   help="System administrator: operates this installation and bypasses all permission checks")
    p.add_argument("--role", choices=ROLE_CHOICES, help="Give a role for the whole organization")
    p.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")

    for name, help_text in (("grant-role", "Give someone a role"), ("revoke-role", "Take a role away")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--org", required=True)
        p.add_argument("--email", required=True)
        p.add_argument("--role", required=True, choices=ROLE_CHOICES)
        where = p.add_mutually_exclusive_group()
        where.add_argument("--college", help="Scope: a college (code or name); default is the whole organization")
        where.add_argument("--department", help="Scope: a department (code or name)")
        where.add_argument("--course", help="Scope: a course (code or name)")

    p = sub.add_parser("roles", help="Show who has which roles")
    p.add_argument("--org", required=True)
    p.add_argument("--email")

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

    p = sub.add_parser("configure-org", help="An organization's domains and settings")
    p.add_argument("--org", required=True)
    p.add_argument("--add-domain", action="append", help="Hostname that serves this organization (repeatable)")
    p.add_argument("--remove-domain", action="append", help="Stop serving this organization at a hostname")
    p.add_argument("--primary", help="The domain that is its public address (LTI URLs are built from it)")
    p.add_argument("--lms-origin", action="append",
                   help="LMS origin allowed to show Stacks in a frame (repeatable; replaces the list)")
    p.add_argument("--clear-lms-origins", action="store_true", help="Use the FRAME_ANCESTORS default again")
    p.add_argument("--contact-email", help="Contact address for Crossref/OpenAlex ('' to use the default)")

    p = sub.add_parser("show-org", help="Show an organization's domains and settings")
    p.add_argument("--org", required=True)

    p = sub.add_parser("list-sources", help="Show an organization's library sources (never the keys)")
    p.add_argument("--org", required=True)

    p = sub.add_parser("lookup", help="Run a citation lookup as the organization would")
    p.add_argument("--org", required=True)
    p.add_argument("query", help="DOI, ISBN, MMS ID, or text containing them")

    sub.add_parser("generate-credentials-key", help="Print a new CREDENTIALS_KEY value")

    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(create_user(args))
    elif args.command == "grant-role":
        asyncio.run(grant_role(args))
    elif args.command == "revoke-role":
        asyncio.run(revoke_role(args))
    elif args.command == "roles":
        asyncio.run(list_roles(args))
    elif args.command == "register-lti-platform":
        asyncio.run(register_lti_platform(args))
    elif args.command == "configure-source":
        asyncio.run(configure_source(args))
    elif args.command == "configure-links":
        asyncio.run(configure_links(args))
    elif args.command == "sync-catalogue":
        asyncio.run(sync_catalogue(args))
    elif args.command == "configure-org":
        asyncio.run(configure_org(args))
    elif args.command == "show-org":
        asyncio.run(show_org(args))
    elif args.command == "list-sources":
        asyncio.run(list_sources(args))
    elif args.command == "lookup":
        asyncio.run(lookup(args))
    elif args.command == "generate-credentials-key":
        from app.services.credentials import generate_key
        print(generate_key())


if __name__ == "__main__":
    main()
