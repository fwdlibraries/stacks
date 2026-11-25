"""People and their roles.

Managing roles needs people.manage, and works only at or below the scopes where
the manager holds it: a college Administrator can make someone Librarian for a
department in their college, but not for another college or the whole
organization. Turning accounts on or off needs people.manage organization-wide.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.models import (
    College,
    CourseOffering,
    CourseTemplate,
    Department,
    LtiUserMapping,
    Organization,
    Role,
    ScopeType,
    User,
    UserRoleAssignment,
)
from app.services import access

router = APIRouter()


async def people_manager(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> access.Grants:
    grants = await access.load_grants(db, user)
    if not grants.anywhere("people.manage"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission required: people.manage")
    return grants


# ── Scopes ───────────────────────────────────────────────────────────────────


class Scope(BaseModel):
    type: ScopeType
    id: uuid.UUID
    label: str  # "Arts", "Arts › History", "HIST101 · fall-2026"


async def _labels(db: AsyncSession, keys: set[tuple[ScopeType, uuid.UUID]]) -> dict[tuple[ScopeType, uuid.UUID], str]:
    """Readable names for scopes, with their parents for context."""
    by_type: dict[ScopeType, set[uuid.UUID]] = {}
    for scope_type, scope_id in keys:
        by_type.setdefault(scope_type, set()).add(scope_id)
    labels: dict[tuple[ScopeType, uuid.UUID], str] = {}
    if ids := by_type.get(ScopeType.organization):
        for org in await db.scalars(select(Organization).where(Organization.id.in_(ids))):
            labels[(ScopeType.organization, org.id)] = f"All of {org.name}"
    if ids := by_type.get(ScopeType.college):
        for c in await db.scalars(select(College).where(College.id.in_(ids))):
            labels[(ScopeType.college, c.id)] = c.name
    if ids := by_type.get(ScopeType.department):
        for d, c in await db.execute(select(Department, College.name).join(Department.college).where(Department.id.in_(ids))):
            labels[(ScopeType.department, d.id)] = f"{c} › {d.name}"
    if ids := by_type.get(ScopeType.course_template):
        for t in await db.scalars(select(CourseTemplate).where(CourseTemplate.id.in_(ids))):
            labels[(ScopeType.course_template, t.id)] = f"{t.code} {t.name}" if t.name != t.code else t.code
    if ids := by_type.get(ScopeType.course_offering):
        for o, t in await db.execute(
            select(CourseOffering, CourseTemplate.code).join(CourseOffering.template).where(CourseOffering.id.in_(ids))
        ):
            labels[(ScopeType.course_offering, o.id)] = f"{t} · {o.term}" + (f" · {o.section}" if o.section else "")
    return labels


@router.get("/scopes", response_model=list[Scope], summary="Where this person may give roles")
async def scopes(grants: access.Grants = Depends(people_manager), db: AsyncSession = Depends(get_db)):
    """The organization, colleges, departments and courses the manager can assign roles for
    (course offerings come from the LMS and aren't offered here)."""
    org_id = grants.user.organization_id
    candidates: list[tuple[ScopeType, uuid.UUID]] = [(ScopeType.organization, org_id)]
    candidates += [(ScopeType.college, c) for c in await db.scalars(select(College.id).where(College.organization_id == org_id))]
    candidates += [
        (ScopeType.department, d)
        for d in await db.scalars(select(Department.id).join(Department.college).where(College.organization_id == org_id))
    ]
    candidates += [
        (ScopeType.course_template, t)
        for t in await db.scalars(
            select(CourseTemplate.id).join(CourseTemplate.department).join(Department.college)
            .where(College.organization_id == org_id)
        )
    ]
    allowed = [c for c in candidates if await access.can_manage_scope(db, grants, *c)]
    labels = await _labels(db, set(allowed))
    order = list(ScopeType)
    return sorted(
        (Scope(type=t, id=i, label=labels.get((t, i), str(i))) for t, i in allowed),
        key=lambda s: (order.index(s.type), s.label.lower()),
    )


# ── People ───────────────────────────────────────────────────────────────────


class RoleOut(BaseModel):
    id: uuid.UUID  # the assignment
    role: str
    scope: Scope
    can_remove: bool


class PersonOut(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    is_active: bool
    is_system_admin: bool
    from_lms: bool
    has_password: bool
    last_login_at: datetime | None
    roles: list[RoleOut]


class PeoplePage(BaseModel):
    people: list[PersonOut]
    total: int
    roles: list[str]  # assignable roles
    can_change_accounts: bool


@router.get("/people", response_model=PeoplePage, summary="People in the organization and their roles")
async def people(
    q: str | None = None,
    offset: int = 0,
    limit: int = 50,
    grants: access.Grants = Depends(people_manager),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 100))
    query = select(User).where(User.organization_id == grants.user.organization_id)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(User.display_name).like(term), func.lower(User.email).like(term)))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    users = (await db.scalars(query.order_by(func.lower(User.display_name)).offset(max(0, offset)).limit(limit))).all()
    ids = [u.id for u in users]

    rows = (
        await db.execute(
            select(UserRoleAssignment, Role.name)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id.in_(ids))
        )
    ).all() if ids else []
    labels = await _labels(db, {(a.scope_type, a.scope_id) for a, _ in rows})
    from_lms = set(await db.scalars(select(LtiUserMapping.user_id).where(LtiUserMapping.user_id.in_(ids)))) if ids else set()

    roles_by_user: dict[uuid.UUID, list[RoleOut]] = {}
    for assignment, role_name in rows:
        key = (assignment.scope_type, assignment.scope_id)
        roles_by_user.setdefault(assignment.user_id, []).append(
            RoleOut(
                id=assignment.id,
                role=role_name,
                scope=Scope(type=assignment.scope_type, id=assignment.scope_id, label=labels.get(key, "?")),
                can_remove=await access.can_manage_scope(db, grants, *key),
            )
        )
    return PeoplePage(
        people=[
            PersonOut(
                id=u.id, display_name=u.display_name, email=u.email, is_active=bool(u.is_active),
                is_system_admin=bool(u.is_system_admin), from_lms=u.id in from_lms,
                has_password=bool(u.password_hash), last_login_at=u.last_login_at,
                roles=sorted(roles_by_user.get(u.id, []), key=lambda r: (r.role, r.scope.label)),
            )
            for u in users
        ],
        total=total or 0,
        roles=list(access.SYSTEM_ROLES),
        can_change_accounts=grants.organization_wide("people.manage"),
    )


async def _person(db: AsyncSession, grants: access.Grants, user_id: uuid.UUID) -> User:
    person = await db.get(User, user_id)
    if person is None or person.organization_id != grants.user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    return person


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=50)
    scope_type: ScopeType
    scope_id: uuid.UUID


@router.post("/people/{user_id}/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED,
             summary="Give someone a role")
async def give_role(
    user_id: uuid.UUID, body: GrantIn, grants: access.Grants = Depends(people_manager), db: AsyncSession = Depends(get_db)
):
    if body.role not in access.SYSTEM_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown role: {body.role}")
    person = await _person(db, grants, user_id)
    if not await access.can_manage_scope(db, grants, body.scope_type, body.scope_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only give roles within the areas you manage")
    assignment = await access.grant(db, person, body.role, body.scope_type, body.scope_id, granted_by=grants.user)
    label = (await _labels(db, {(body.scope_type, body.scope_id)})).get((body.scope_type, body.scope_id), "?")
    return RoleOut(id=assignment.id, role=body.role, scope=Scope(type=body.scope_type, id=body.scope_id, label=label),
                   can_remove=True)


@router.delete("/people/{user_id}/roles/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Take a role away")
async def take_role(
    user_id: uuid.UUID, assignment_id: uuid.UUID,
    grants: access.Grants = Depends(people_manager), db: AsyncSession = Depends(get_db),
):
    person = await _person(db, grants, user_id)
    assignment = await db.get(UserRoleAssignment, assignment_id)
    if assignment is None or assignment.user_id != person.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if not await access.can_manage_scope(db, grants, assignment.scope_type, assignment.scope_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only take away roles within the areas you manage")
    role_name = await db.scalar(select(Role.name).where(Role.id == assignment.role_id))
    if (
        person.id == grants.user.id
        and not grants.system_admin
        and role_name == access.ADMINISTRATOR
        and assignment.scope_type == ScopeType.organization
    ):
        # Don't let the last way in disappear by accident
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't remove your own organization Administrator role")
    await db.delete(assignment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool


@router.patch("/people/{user_id}", response_model=PersonOut, summary="Turn an account on or off")
async def update_account(
    user_id: uuid.UUID, body: AccountUpdate,
    grants: access.Grants = Depends(people_manager), db: AsyncSession = Depends(get_db),
):
    if not grants.organization_wide("people.manage"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only organization-wide administrators can turn accounts off")
    person = await _person(db, grants, user_id)
    if person.id == grants.user.id and not body.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't turn off your own account")
    if person.is_system_admin and not grants.system_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "System administrators are managed by your Stacks provider")
    person.is_active = body.is_active
    await db.flush()
    page = await people(q=person.email, offset=0, limit=100, grants=grants, db=db)
    return next(p for p in page.people if p.id == person.id)
