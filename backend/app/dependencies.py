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
    """Resolve a Bearer token (a session JWT) to an active User."""
    return await _resolve_user(credentials, db, token_scope=None)


async def get_extension_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """Like get_current_user, but also accepts browser-extension tokens.

    Use only on the endpoints the extension needs (listing lists, finding and
    adding citations); everything else stays session-only.
    """
    from app.services.api_tokens import EXTENSION_SCOPE
    return await _resolve_user(credentials, db, token_scope=EXTENSION_SCOPE)


async def _resolve_user(credentials, db: AsyncSession, token_scope: str | None):
    from app.services import api_tokens
    from app.services.auth_service import AuthService
    user = None
    if credentials is not None:
        value = credentials.credentials
        if api_tokens.is_token(value):
            user = await api_tokens.user_for(db, value, token_scope) if token_scope else None
        else:
            user = await AuthService.get_user_from_token(value, db)
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
