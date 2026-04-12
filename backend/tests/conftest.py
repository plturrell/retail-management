import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models.user import User


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Use an in-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Mock user for auth
MOCK_USER = None


async def mock_get_current_user():
    async with TestSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(User))
        user = result.scalar_one_or_none()
        if user:
            return user
    raise Exception("No test user found")


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    from app.auth.dependencies import get_current_user as get_user_dep

    app.dependency_overrides[get_user_dep] = mock_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_user_dep, None)


@pytest_asyncio.fixture
async def seed_user():
    async with TestSessionLocal() as session:
        user = User(
            firebase_uid="test-firebase-uid",
            email="test@example.com",
            full_name="Test User",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
