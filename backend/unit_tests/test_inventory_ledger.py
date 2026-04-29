"""Unit tests for the TiDB-backed inventory ledger.

Runs against a temp-file `sqlite+aiosqlite` database — fast, zero CI deps,
and good enough to catch ORM/schema regressions before they hit real TiDB.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Iterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import settings
from app.db import tidb
from app.db.models import Base, StockMovement, StockMovementSource
from app.services import inventory_ledger


@pytest.fixture()
def temp_sqlite_url() -> Iterator[str]:
    """Use a temp-file sqlite DB so multiple async connections see the same data."""
    fd, path = tempfile.mkstemp(prefix="ledger-test-", suffix=".sqlite")
    os.close(fd)
    yield f"sqlite+aiosqlite:///{path}"
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest_asyncio.fixture()
async def configured_tidb(temp_sqlite_url: str, monkeypatch: pytest.MonkeyPatch):
    """Point the TiDB layer at sqlite, reset its lazily-initialised globals,
    and create the schema once. Restores state on teardown."""
    monkeypatch.setattr(settings, "TIDB_DATABASE_URL", temp_sqlite_url)
    # Reset module-level cache so `_ensure_initialised` re-evaluates the URL.
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)

    engine = tidb.get_engine()
    assert engine is not None, "engine should be created when URL is set"

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


# ---------------------------------------------------------------------------
# is_enabled / get_engine / get_session
# ---------------------------------------------------------------------------

def test_is_enabled_false_when_url_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TIDB_DATABASE_URL", "")
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)
    assert tidb.is_enabled() is False
    assert tidb.get_engine() is None


def test_is_enabled_true_when_url_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TIDB_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)
    assert tidb.is_enabled() is True


# ---------------------------------------------------------------------------
# Schema regression — the model must produce the columns/indexes we expect.
# ---------------------------------------------------------------------------

def test_stock_movements_schema_columns():
    table = StockMovement.__table__
    assert table.name == "stock_movements"

    expected_columns = {
        "id", "store_id", "sku_id", "inventory_type",
        "delta_qty", "resulting_qty", "source",
        "reference_type", "reference_id", "reason",
        "actor_user_id", "created_at", "event_time",
    }
    actual_columns = {c.name for c in table.columns}
    assert actual_columns == expected_columns

    # Critical analytical indexes must exist.
    index_names = {idx.name for idx in table.indexes}
    assert "ix_stock_movements_store_sku_event" in index_names
    assert "ix_stock_movements_store_event" in index_names


# ---------------------------------------------------------------------------
# record_movement — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_movement_writes_row(configured_tidb):
    store_id = uuid4()
    sku_id = uuid4()

    row_id = await inventory_ledger.record_movement(
        store_id=store_id,
        sku_id=sku_id,
        delta_qty=5,
        resulting_qty=15,
        source="manual",
        reference_type="inventory_adjustment",
        reference_id=uuid4(),
        reason="restock",
        actor_user_id=uuid4(),
    )
    assert row_id is not None

    sessionmaker = async_sessionmaker(configured_tidb, expire_on_commit=False)
    async with sessionmaker() as session:
        loaded = await session.get(StockMovement, row_id)
        assert loaded is not None
        assert loaded.store_id == str(store_id)
        assert loaded.sku_id == str(sku_id)
        assert loaded.delta_qty == 5
        assert loaded.resulting_qty == 15
        assert loaded.source == StockMovementSource.manual.value
        assert loaded.reference_type == "inventory_adjustment"
        assert loaded.reason == "restock"
        assert loaded.created_at is not None
        assert loaded.event_time is not None


@pytest.mark.asyncio
async def test_record_movement_coerces_unknown_source_to_manual(configured_tidb):
    row_id = await inventory_ledger.record_movement(
        store_id=uuid4(),
        sku_id=uuid4(),
        delta_qty=-3,
        source="totally-fake-source",
    )
    assert row_id is not None

    sessionmaker = async_sessionmaker(configured_tidb, expire_on_commit=False)
    async with sessionmaker() as session:
        loaded = await session.get(StockMovement, row_id)
        assert loaded is not None
        assert loaded.source == StockMovementSource.manual.value


@pytest.mark.asyncio
async def test_record_movement_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TIDB_DATABASE_URL", "")
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)

    row_id = await inventory_ledger.record_movement(
        store_id=uuid4(),
        sku_id=uuid4(),
        delta_qty=1,
        source="manual",
    )
    assert row_id is None


@pytest.mark.asyncio
async def test_record_movement_swallows_db_errors(monkeypatch: pytest.MonkeyPatch, caplog):
    """A failing SQL write must NOT raise — dual-write callers rely on this."""
    # Point at an unreachable URL with a syntactically valid driver.
    monkeypatch.setattr(
        settings, "TIDB_DATABASE_URL",
        "mysql+asyncmy://user:pass@127.0.0.1:1/nope",
    )
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)

    row_id = await inventory_ledger.record_movement(
        store_id=uuid4(),
        sku_id=uuid4(),
        delta_qty=1,
        source="manual",
    )
    assert row_id is None
    assert any("TiDB stock-movement write failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# list_movements_for_sku
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_movements_for_sku_returns_desc_by_event_time(configured_tidb):
    store_id = uuid4()
    sku_id = uuid4()
    now = datetime.now(timezone.utc)

    # Seed three rows with different event_times.
    for offset_minutes, delta in [(-30, 1), (-10, 2), (-20, 3)]:
        await inventory_ledger.record_movement(
            store_id=store_id,
            sku_id=sku_id,
            delta_qty=delta,
            source="manual",
            event_time=now + timedelta(minutes=offset_minutes),
        )
    # Plus one for a different SKU we should never see.
    await inventory_ledger.record_movement(
        store_id=store_id,
        sku_id=uuid4(),
        delta_qty=99,
        source="manual",
    )

    rows = await inventory_ledger.list_movements_for_sku(
        store_id=store_id, sku_id=sku_id, limit=10,
    )
    assert len(rows) == 3
    # Descending by event_time means most-recent first: delta 2 (-10m), 3 (-20m), 1 (-30m).
    assert [r.delta_qty for r in rows] == [2, 3, 1]


@pytest.mark.asyncio
async def test_list_movements_returns_empty_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TIDB_DATABASE_URL", "")
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)

    rows = await inventory_ledger.list_movements_for_sku(
        store_id=uuid4(), sku_id=uuid4(),
    )
    assert rows == []


# ---------------------------------------------------------------------------
# healthcheck
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_healthcheck_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TIDB_DATABASE_URL", "")
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)

    result = await tidb.healthcheck()
    assert result["status"] == "disabled"


@pytest.mark.asyncio
async def test_healthcheck_ok_when_reachable(configured_tidb):
    result = await tidb.healthcheck()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_healthcheck_error_when_unreachable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        settings, "TIDB_DATABASE_URL",
        "mysql+asyncmy://user:pass@127.0.0.1:1/nope",
    )
    monkeypatch.setattr(tidb, "_engine", None)
    monkeypatch.setattr(tidb, "_sessionmaker", None)

    result = await tidb.healthcheck()
    assert result["status"] == "error"
    assert "detail" in result
