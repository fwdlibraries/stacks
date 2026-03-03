from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

router = APIRouter()


@router.post("/local/login", summary="Local username/password login")
async def local_login(db: AsyncSession = Depends(get_db)):
    """Authenticate with username and password. Returns access + refresh tokens."""
    # TODO: implement
    pass


@router.post("/logout", summary="Logout")
async def logout():
    """Invalidate the current session token."""
    # TODO: implement
    pass


@router.get("/me", summary="Current user")
async def get_me():
    """Return the current authenticated user and their permissions."""
    # TODO: implement
    pass


@router.post("/token/refresh", summary="Refresh access token")
async def refresh_token():
    """Exchange a refresh token for a new access token."""
    # TODO: implement
    pass
