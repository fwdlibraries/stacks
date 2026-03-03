from fastapi import APIRouter

router = APIRouter()


@router.get("/live", summary="Liveness probe")
async def liveness():
    """Returns 200 when the application process is running."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def readiness():
    """
    Returns 200 when the application is ready to serve traffic.
    Checks database and Redis connectivity.
    """
    # TODO: add DB and Redis health checks
    return {"status": "ok"}
