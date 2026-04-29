from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.firestore_payroll_support import override_owner_user


@pytest.mark.asyncio
async def test_data_quality_reference_excludes_workshop_stocking_location(
    client: AsyncClient,
) -> None:
    with override_owner_user(owner_id=uuid4(), store_id=uuid4()):
        response = await client.get("/api/data-quality/products")

    assert response.status_code == 200, response.text
    reference = response.json()["reference"]
    assert "workshop" not in reference["stocking_locations"]
    assert "warehouse" in reference["stocking_locations"]
