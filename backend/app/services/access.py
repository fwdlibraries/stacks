"""Roles, permissions and scopes: who may do what, where.

A user holds roles through assignments, each scoped to a level of the
organization: the whole organization, a college, a department, a course
(template) or one course offering. A permission granted at a level applies to
everything beneath it, so a department Librarian can edit every list in that
department, and an Instructor assigned to an offering can edit that course's list.

Settings that only make sense organization-wide (library connections, LMS
registrations) need the permission at organization scope: a college admin
can't reconfigure them for everyone.

System admins (users.is_system_admin) operate the installation and bypass all
checks.
"""
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    College,
    CourseOffering,
    CourseTemplate,
    Department,
    OfferingListOverride,
    Permission,
    ReadingList,
    Role,
    RolePermission,
    ScopeType,
    User,
    UserRoleAssignment,
)

# ── Catalog ──────────────────────────────────────────────────────────────────

PERMISSIONS: dict[str, tuple[str, str]] = {
    # code: (category, description)
    "lists.view": ("lists", "See reading lists, including drafts, history and click counts"),
    "lists.edit": ("lists", "Edit reading lists: sections, citations, imports"),
    "lists.publish": ("lists", "Publish, unpublish and change who can see reading lists"),
    "lists.create": ("lists", "Create reading lists"),
    "reports.view": ("reports", "See flagged citations and usage across lists"),
    "courses.manage": ("admin", "Manage courses, offerings and terms"),
    "people.manage": ("admin", "Give people roles"),
    "settings.manage": ("admin", "Configure library connections, link resolution and LMS registrations"),
}

ADMINISTRATOR, LIBRARIAN, INSTRUCTOR, VIEWER = "Administrator", "Librarian", "Instructor", "Viewer"

SYSTEM_ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    ADMINISTRATOR: ("Everything within their scope", tuple(PERMISSIONS)),
    LIBRARIAN: (
        "Builds and maintains reading lists",
        ("lists.view", "lists.edit", "lists.publish", "lists.create", "reports.view"),
    ),
    INSTRUCTOR: ("Edits their courses' reading lists", ("lists.view", "lists.edit", "lists.publish")),
    VIEWER: ("Sees reading lists and reports without changing them", ("lists.view", "reports.view")),
}

# Permissions that apply only to the whole organization
ORGANIZATION_ONLY = {"settings.manage"}


async def ensure_catalog(db: AsyncSession) -> dict[str, Role]:
    """Create the permissions and built-in roles if missing; returns roles by name. Idempotent."""
    perms = {p.code: p for p in await db.scalars(select(Permission))}
    for code, (category, description) in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, category=category, description=description)
            db.add(perms[code])
    await db.flush()

    roles = {
        r.name: r
        for r in await db.scalars(select(Role).where(Role.is_system_role.is_(True), Role.organization_id.is_(None)))
    }
    for name, (description, codes) in SYSTEM_ROLES.items():
        role = roles.get(name)
        if role is None:
            role = roles[name] = Role(name=name, description=description, is_system_role=True)
            db.add(role)
            await db.flush()
        have = set(await db.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)))
        for code in codes:
            if perms[code].id not in have:
                db.add(RolePermission(role_id=role.id, permission_id=perms[code].id))
    await db.flush()
    return roles


async def grant(
    db: AsyncSession,
    user: User,
    role_name: str,
    scope_type: ScopeType,
    scope_id: uuid.UUID,
    granted_by: User | None = None,
) -> UserRoleAssignment:
    """Give a role at a scope (no-op if the user already has exactly that)."""
    roles = await ensure_catalog(db)
    role = roles[role_name]
    existing = await db.scalar(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user.id,
            UserRoleAssignment.role_id == role.id,
            UserRoleAssignment.scope_type == scope_type,
            UserRoleAssignment.scope_id == scope_id,
        )
    )
    if existing:
        return existing
    assignment = UserRoleAssignment(
        user_id=user.id,
        role_id=role.id,
        scope_type=scope_type,
        scope_id=scope_id,
        granted_by=granted_by.id if granted_by else None,
    )
    db.add(assignment)
    await db.flush()
    return assignment


# ── Grants ───────────────────────────────────────────────────────────────────


@dataclass
class Grants:
    """What one user may do: permission code → scopes where they hold it."""

    user: User
    system_admin: bool = False
    scopes: dict[str, set[tuple[ScopeType, uuid.UUID]]] = field(default_factory=lambda: defaultdict(set))

    def anywhere(self, permission: str) -> bool:
        return self.system_admin or bool(self.scopes.get(permission))

    def organization_wide(self, permission: str) -> bool:
        return self.system_admin or (ScopeType.organization, self.user.organization_id) in self.scopes.get(
            permission, set()
        )


async def load_grants(db: AsyncSession, user: User) -> Grants:
    """The user's grants, loaded once per request (cached on the user object)."""
    cached = getattr(user, "_stacks_grants", None)
    if cached is not None:
        return cached
    grants = Grants(user=user, system_admin=bool(user.is_system_admin))
    now = datetime.now(UTC)
    rows = await db.execute(
        select(Permission.code, UserRoleAssignment.scope_type, UserRoleAssignment.scope_id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
        .where(
            UserRoleAssignment.user_id == user.id,
            or_(UserRoleAssignment.expires_at.is_(None), UserRoleAssignment.expires_at > now),
        )
    )
    for code, scope_type, scope_id in rows:
        # A role scoped below the organization never grants organization-only permissions
        if code in ORGANIZATION_ONLY and scope_type != ScopeType.organization:
            continue
        grants.scopes[code].add((scope_type, scope_id))
    user._stacks_grants = grants  # type: ignore[attr-defined]
    return grants


def list_condition(grants: Grants, permission: str) -> ColumnElement[bool]:
    """SQL condition: the user holds `permission` for the reading list in the row.

    The query must join ReadingList → CourseTemplate → Department → College and be
    limited to the user's organization (lists_service.org_lists_query does both).
    """
    if grants.organization_wide(permission):
        return true()
    by_type: dict[ScopeType, set[uuid.UUID]] = defaultdict(set)
    for scope_type, scope_id in grants.scopes.get(permission, set()):
        by_type[scope_type].add(scope_id)
    parts: list[ColumnElement[bool]] = []
    if ids := by_type.get(ScopeType.college):
        parts.append(College.id.in_(ids))
    if ids := by_type.get(ScopeType.department):
        parts.append(Department.id.in_(ids))
    if ids := by_type.get(ScopeType.course_template):
        parts.append(CourseTemplate.id.in_(ids))
    if ids := by_type.get(ScopeType.course_offering):
        # The offering's lists: its course's lists and any list it overrides with
        parts.append(
            ReadingList.course_template_id.in_(
                select(CourseOffering.course_template_id).where(CourseOffering.id.in_(ids))
            )
        )
        parts.append(
            ReadingList.id.in_(
                select(OfferingListOverride.reading_list_id).where(
                    OfferingListOverride.course_offering_id.in_(ids), OfferingListOverride.is_active.is_(True)
                )
            )
        )
    return or_(*parts) if parts else false()
