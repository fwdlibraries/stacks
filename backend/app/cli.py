"""Admin command line.

    python -m app.cli create-user --org demo --email you@example.edu --name "Your Name" [--admin]
    python -m app.cli register-lti-platform --org demo --issuer https://lms.example.edu \
        --client-id ... --auth-login-url ... --auth-token-url ... --jwks-url ... \
        --deployment-id 1 [--deployment-id 2 ...]

The password is prompted for (or read from stdin with --password-stdin), never
passed as an argument, so it doesn't end up in shell history or `ps` output.
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

    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(create_user(args))
    elif args.command == "register-lti-platform":
        asyncio.run(register_lti_platform(args))


if __name__ == "__main__":
    main()
