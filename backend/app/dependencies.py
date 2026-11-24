from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

# auto_error=False so a missing header is a 401 (not 403), like an invalid token
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a Bearer token to an active User."""
    from app.services.auth_service import AuthService
    user = (
        await AuthService.get_user_from_token(credentials.credentials, db)
        if credentials is not None
        else None
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    return user


async def get_current_admin(current_user=Depends(get_current_user)):
    """Require system admin role."""
    if not current_user.is_system_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System administrator access required",
        )
    return current_user


def require_permission(permission_code: str):
    """
    Dependency factory for permission-based authorization.

    Usage:
        @router.post("/lists")
        async def create_list(
            user = Depends(require_permission("list:create"))
        ):
    """
    async def _check(
        current_user=Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        from app.services.auth_service import AuthService
        has_perm = await AuthService.user_has_permission(
            current_user, permission_code, db
        )
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission_code}",
            )
        return current_user
    return _check
