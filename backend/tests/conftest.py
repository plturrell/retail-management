import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from alembic import command
from alembic.config import Config
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.user import User


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Use an in-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite://"
ALEMBIC_INI_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parents[1] / "alembic"

engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _alembic_config(connection) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", TEST_DB_URL)
    config.attributes["connection"] = connection
    return config


def _run_upgrade(connection, revision: str) -> None:
    command.upgrade(_alembic_config(connection), revision)


def _run_downgrade(connection, revision: str) -> None:
    command.downgrade(_alembic_config(connection), revision)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade, "head")
    yield
    async with engine.begin() as conn:
        await conn.run_sync(_run_downgrade, "base")


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


# Mock auth state for tests
MOCK_AUTH_CLAIMS = {
    "uid": "test-firebase-uid",
    "email": "test@example.com",
}


async def mock_get_current_user():
    async with TestSessionLocal() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(User)
            .options(selectinload(User.store_roles))
            .where(User.firebase_uid == MOCK_AUTH_CLAIMS["uid"])
        )
        user = result.scalar_one_or_none()
        if user:
            return user
    raise Exception("No test user found")


async def mock_get_token_claims():
    return MOCK_AUTH_CLAIMS.copy()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    from app.auth.dependencies import (
        get_current_user as get_user_dep,
        get_token_claims as get_token_claims_dep,
    )

    app.dependency_overrides[get_user_dep] = mock_get_current_user
    app.dependency_overrides[get_token_claims_dep] = mock_get_token_claims

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_user_dep, None)
    app.dependency_overrides.pop(get_token_claims_dep, None)


@pytest.fixture
def auth_claims():
    original = MOCK_AUTH_CLAIMS.copy()
    yield MOCK_AUTH_CLAIMS
    MOCK_AUTH_CLAIMS.clear()
    MOCK_AUTH_CLAIMS.update(original)


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
