import pytest
from httpx import AsyncClient

from app.models.store import Store
from app.models.user import RoleEnum, UserStoreRole
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_profit_loss_report(client: AsyncClient, seed_user):
    async with TestSessionLocal() as session:
        store = Store(
            name="Report Store",
            location="There",
            address="2 Ave",
            business_hours_start="09:00:00",
            business_hours_end="17:00:00",
            is_active=True,
        )
        session.add(store)
        await session.flush()
        session.add(
            UserStoreRole(
                user_id=seed_user.id,
                store_id=store.id,
                role=RoleEnum.owner,
            )
        )
        await session.commit()
        store_id = str(store.id)

    resp = await client.get(
        f"/api/stores/{store_id}/reports/profit-loss",
        params={"from": "2024-01-01", "to": "2024-12-31"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert "data" in body
    pl = body["data"]
    assert "revenue" in pl
    assert "expenses" in pl
    assert "net_income" in pl
