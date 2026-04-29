"""Test fixtures for the Firestore-backed backend.

The Postgres/SQLAlchemy fixtures have been removed as part of the
Firestore migration. Only Firestore-native or pure-logic tests remain.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


MOCK_AUTH_CLAIMS = {
    "uid": "test-firebase-uid",
    "email": "test@example.com",
}


async def mock_get_token_claims():
    return MOCK_AUTH_CLAIMS.copy()


async def mock_get_current_user():
    return {
        "id": "test-user-id",
        "firebase_uid": MOCK_AUTH_CLAIMS["uid"],
        "email": MOCK_AUTH_CLAIMS["email"],
        "full_name": "Test User",
        "phone": None,
        "store_roles": [],
    }


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
