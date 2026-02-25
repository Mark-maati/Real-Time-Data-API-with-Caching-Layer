import os

# Set required env vars BEFORE any app imports trigger Settings()
os.environ.setdefault("API_KEY", "test-api-key-for-testing")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.database import Base, get_db
from app.auth import require_api_key

TEST_DB = "sqlite+aiosqlite:///:memory:"
TEST_API_KEY = "test-api-key-for-testing"


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine):
    Session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


class AsyncIterEmpty:
    """Async iterator that yields nothing (for scan_iter mock)."""
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


@pytest_asyncio.fixture
async def client(db):
    async def override_get_db():
        yield db

    async def override_api_key():
        return TEST_API_KEY

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_api_key] = override_api_key

    # Mock Redis so route tests don't need a live Redis
    with patch("app.cache._pool", new=True), \
         patch("app.cache.get_redis") as mock_redis:
        # pipeline() is synchronous in redis-py, returns a pipeline object
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[None, False])

        mock_r = AsyncMock()
        mock_r.ping = AsyncMock(return_value=True)
        mock_r.get = AsyncMock(return_value=None)
        mock_r.setex = AsyncMock(return_value=True)
        mock_r.delete = AsyncMock(return_value=1)
        # pipeline() and scan_iter() are sync calls that return objects
        mock_r.pipeline = MagicMock(return_value=mock_pipe)
        mock_r.scan_iter = MagicMock(return_value=AsyncIterEmpty())

        mock_redis.return_value = mock_r

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

    app.dependency_overrides.clear()
