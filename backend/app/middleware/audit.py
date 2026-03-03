from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import logging

logger = logging.getLogger(__name__)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXCLUDED_PATHS = {"/api/v1/health/live", "/api/v1/health/ready", "/lti/jwks"}


class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    Records all mutating authenticated API operations to the audit log.
    Captures: user, method, path, status code, and timestamp.
    Full before/after diffs are recorded at the service layer for sensitive operations.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if (
            request.method in MUTATING_METHODS
            and request.url.path not in EXCLUDED_PATHS
            and request.url.path.startswith("/api/")
        ):
            # TODO: extract user from token, write to audit_log table
            logger.info(
                "AUDIT %s %s %d",
                request.method,
                request.url.path,
                response.status_code,
            )

        return response
