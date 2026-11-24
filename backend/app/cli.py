"""Admin command line.

    python -m app.cli create-user --org demo --email you@example.edu --name "Your Name" [--admin]

The password is prompted for (or read from stdin with --password-stdin), never
passed as an argument, so it doesn't end up in shell history or `ps` output.
"""
import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.models import IdentityProvider, Organization, User, UserIdentity
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="Create a local (email + password) user")
    p.add_argument("--org", required=True, help="Organization slug, e.g. demo")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True, help="Display name")
    p.add_argument("--admin", action="store_true", help="Make the user a system administrator")
    p.add_argument("--password-stdin", action="store_true", help="Read the password from stdin")

    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(create_user(args))


if __name__ == "__main__":
    main()
