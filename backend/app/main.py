from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, lti, orgs, lists, citations, imports, files, users, admin, health, public
from app.middleware.audit import AuditLogMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup hooks (e.g. warm Redis connection)
    yield
    # Shutdown hooks


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stacks",
        description="Open-source course reading list and citation management platform",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuditLogMiddleware)

    # LTI endpoints — unversioned, must remain stable for LMS registrations
    app.include_router(lti.router,       prefix="/lti",              tags=["LTI"])

    # API v1
    app.include_router(auth.router,      prefix="/api/v1/auth",      tags=["Auth"])
    app.include_router(orgs.router,      prefix="/api/v1",           tags=["Organizations"])
    app.include_router(lists.router,     prefix="/api/v1",           tags=["Reading Lists"])
    app.include_router(citations.router, prefix="/api/v1",           tags=["Citations"])
    app.include_router(imports.router,   prefix="/api/v1/citations", tags=["Import"])
    app.include_router(files.router,     prefix="/api/v1/files",     tags=["Files"])
    app.include_router(users.router,     prefix="/api/v1",           tags=["Users"])
    app.include_router(admin.router,     prefix="/api/v1/admin",     tags=["Admin"])
    app.include_router(health.router,    prefix="/api/v1/health",    tags=["Health"])

    # Unauthenticated student list view
    app.include_router(public.router,    prefix="/api/v1/public",    tags=["Public"])

    return app


app = create_app()
