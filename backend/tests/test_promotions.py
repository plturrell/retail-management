from __future__ import annotations

import pytest

from app.models.inventory import Promotion
from app.services.promotions import best_discount_for_sku
from tests.conftest import TestSessionLocal
from tests.test_orders import _seed_category, _seed_sku, _seed_store_and_user


async def _seed_promotion(
    *,
    disc_id: str,
    disc_method: str,
    disc_value: float,
    sku_id=None,
    category_id=None,
    line_type: str = "SKU",
    line_group: str | None = None,
):
    async with TestSessionLocal() as session:
        promo = Promotion(
            disc_id=disc_id,
            sku_id=sku_id,
            category_id=category_id,
            line_type=line_type,
            disc_method=disc_method,
            disc_value=disc_value,
            line_group=line_group,
        )
        session.add(promo)
        await session.commit()


@pytest.mark.asyncio
async def test_percent_discount(seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    await _seed_promotion(
        disc_id="PCT01",
        sku_id=sku.id,
        disc_method="PERCENT",
        disc_value=25.0,
    )
    async with TestSessionLocal() as db:
        disc = await best_discount_for_sku(
            db, sku.id, None, unit_price=80.0, qty=1
        )
    assert disc == 20.0


@pytest.mark.asyncio
async def test_amount_discount(seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    await _seed_promotion(
        disc_id="AMT01",
        sku_id=sku.id,
        disc_method="AMOUNT",
        disc_value=75.0,
    )
    async with TestSessionLocal() as db:
        disc = await best_discount_for_sku(
            db, sku.id, None, unit_price=50.0, qty=1
        )
    assert disc == 50.0


@pytest.mark.asyncio
async def test_bogo_discount(seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    await _seed_promotion(
        disc_id="BOGO1",
        sku_id=sku.id,
        disc_method="BOGO",
        disc_value=0.0,
    )
    async with TestSessionLocal() as db:
        disc = await best_discount_for_sku(
            db, sku.id, None, unit_price=100.0, qty=4
        )
    assert disc == 50.0


@pytest.mark.asyncio
async def test_best_discount_picks_highest(seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    await _seed_promotion(
        disc_id="AMT02",
        sku_id=sku.id,
        disc_method="AMOUNT",
        disc_value=15.0,
    )
    await _seed_promotion(
        disc_id="PCT02",
        sku_id=sku.id,
        disc_method="PERCENT",
        disc_value=20.0,
    )
    async with TestSessionLocal() as db:
        disc = await best_discount_for_sku(
            db, sku.id, None, unit_price=100.0, qty=1
        )
    assert disc == 20.0


@pytest.mark.asyncio
async def test_category_level_promotion(seed_user):
    store = await _seed_store_and_user(seed_user)
    category = await _seed_category(store.id)
    sku = await _seed_sku(store.id, category_id=category.id)
    await _seed_promotion(
        disc_id="CAT01",
        sku_id=None,
        category_id=category.id,
        line_type="CAT",
        disc_method="PERCENT",
        disc_value=10.0,
    )
    async with TestSessionLocal() as db:
        disc = await best_discount_for_sku(
            db,
            sku.id,
            category.id,
            unit_price=200.0,
            qty=1,
        )
    assert disc == 20.0


@pytest.mark.asyncio
async def test_no_promotions_returns_zero(seed_user):
    store = await _seed_store_and_user(seed_user)
    sku = await _seed_sku(store.id)
    async with TestSessionLocal() as db:
        disc = await best_discount_for_sku(
            db, sku.id, None, unit_price=99.0, qty=2
        )
    assert disc == 0.0
