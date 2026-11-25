import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.services.ephemeral import MemoryStore, get_ephemeral_store

# Override to point at the compose database, e.g. postgresql+asyncpg://stacks:<pw>@db:5432/stacks_test
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://stacks:stacks@localhost:5432/stacks_test"
)

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # A fresh in-memory store per test (login attempt counters, LTI state, link cache)
    store = MemoryStore()
    app.dependency_overrides[get_ephemeral_store] = lambda: store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def make_org_admin(db: AsyncSession, user, organization) -> None:
    """Give a test user the Administrator role for their whole organization."""
    from app.models.models import ScopeType
    from app.services import access

    await db.flush()
    await access.grant(db, user, access.ADMINISTRATOR, ScopeType.organization, organization.id)
    await db.commit()
