from datetime import date

import pytest
from httpx import AsyncClient

from app.models.finance import Account, AccountType
from app.models.store import Store
from app.models.user import RoleEnum, UserStoreRole
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_create_and_list_accounts(client: AsyncClient, seed_user):
    payload = {
        "code": "9999",
        "name": "Test Cash",
        "account_type": "asset",
        "is_active": True,
    }
    resp = await client.post("/api/accounts", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["code"] == "9999"

    resp = await client.get("/api/accounts")
    assert resp.status_code == 200
    listed = resp.json()["data"]
    assert any(a["code"] == "9999" for a in listed)


@pytest.mark.asyncio
async def test_create_journal_entry_balanced(client: AsyncClient, seed_user):
    async with TestSessionLocal() as session:
        store = Store(
            name="Finance Store",
            location="Here",
            address="1 St",
            business_hours_start="09:00:00",
            business_hours_end="17:00:00",
            is_active=True,
        )
        session.add(store)
        await session.flush()

        cash = Account(
            code="F1000",
            name="Cash",
            account_type=AccountType.asset,
            is_active=True,
            store_id=store.id,
        )
        equity = Account(
            code="F3000",
            name="Equity",
            account_type=AccountType.equity,
            is_active=True,
            store_id=store.id,
        )
        session.add_all([cash, equity])
        await session.flush()

        session.add(
            UserStoreRole(
                user_id=seed_user.id,
                store_id=store.id,
                role=RoleEnum.manager,
            )
        )
        await session.commit()

        cash_id = str(cash.id)
        equity_id = str(equity.id)
        store_id = str(store.id)

    je = {
        "entry_date": str(date.today()),
        "description": "Opening balance",
        "source_type": "manual",
        "lines": [
            {"account_id": cash_id, "debit": "100.00", "credit": "0"},
            {"account_id": equity_id, "debit": "0", "credit": "100.00"},
        ],
    }
    resp = await client.post(f"/api/stores/{store_id}/journal-entries", json=je)
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["description"] == "Opening balance"
    assert len(data["lines"]) == 2
