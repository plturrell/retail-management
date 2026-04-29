"""Service layer for the TiDB-backed inventory ledger.

All public functions are safe to call when the TiDB layer is disabled —
they return early and log at INFO. This is intentional: routers dual-write
during the migration and must not fail when SQL is unavailable.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select

from app.db import tidb
from app.db.models.inventory_ledger import StockMovement, StockMovementSource

logger = logging.getLogger(__name__)


def _coerce_source(value: str) -> str:
    """Map free-form source strings onto the enum, falling back to manual."""
    try:
        return StockMovementSource(value).value
    except ValueError:
        return StockMovementSource.manual.value


async def record_movement(
    *,
    store_id: UUID | str,
    sku_id: UUID | str,
    delta_qty: int,
    source: str,
    inventory_type: str = "finished",
    resulting_qty: Optional[int] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[UUID | str] = None,
    reason: Optional[str] = None,
    actor_user_id: Optional[UUID | str] = None,
    event_time: Optional[datetime] = None,
) -> Optional[str]:
    """Append a single stock-movement row.

    Returns the new row id on success, `None` when the TiDB layer is disabled
    or the write failed. Failures are logged but never raised, so callers in
    the dual-write path don't need to wrap this in try/except themselves.
    """
    if not tidb.is_enabled():
        return None

    try:
        engine = tidb.get_engine()
    except Exception as exc:  # noqa: BLE001 — dual-write must not break callers
        logger.warning(
            "TiDB stock-movement write failed (store=%s sku=%s delta=%s source=%s): %s",
            store_id, sku_id, delta_qty, source, exc,
        )
        return None
    if engine is None:
        return None

    row_id = str(_uuid.uuid4())
    movement = StockMovement(
        id=row_id,
        store_id=str(store_id),
        sku_id=str(sku_id),
        inventory_type=inventory_type,
        delta_qty=int(delta_qty),
        resulting_qty=int(resulting_qty) if resulting_qty is not None else None,
        source=_coerce_source(source),
        reference_type=reference_type,
        reference_id=str(reference_id) if reference_id is not None else None,
        reason=reason,
        actor_user_id=str(actor_user_id) if actor_user_id is not None else None,
        event_time=event_time or datetime.now(timezone.utc),
    )

    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(movement)
            await session.commit()
        return row_id
    except Exception as exc:  # noqa: BLE001 — dual-write must not break callers
        logger.warning(
            "TiDB stock-movement write failed (store=%s sku=%s delta=%s source=%s): %s",
            store_id, sku_id, delta_qty, source, exc,
        )
        return None


async def list_movements_for_sku(
    *,
    store_id: UUID | str,
    sku_id: UUID | str,
    limit: int = 100,
) -> Sequence[StockMovement]:
    """Return the most recent movements for `(store, sku)`. Empty list if disabled."""
    if not tidb.is_enabled():
        return []
    engine = tidb.get_engine()
    if engine is None:
        return []

    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine, expire_on_commit=False) as session:
            stmt = (
                select(StockMovement)
                .where(
                    StockMovement.store_id == str(store_id),
                    StockMovement.sku_id == str(sku_id),
                )
                .order_by(StockMovement.event_time.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
    except Exception as exc:  # noqa: BLE001
        logger.warning("TiDB stock-movement read failed (store=%s sku=%s): %s", store_id, sku_id, exc)
        return []
