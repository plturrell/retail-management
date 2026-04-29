from __future__ import annotations

from datetime import date, datetime, time, timezone
from uuid import uuid4

from app.routers.stores import _serialize_store_data, _store_to_read
from app.schemas.store import StoreOperationalStatus, StoreType


def test_store_round_trip_preserves_operational_metadata():
    raw = _serialize_store_data(
        {
            "id": str(uuid4()),
            "name": "Breeze by the East",
            "location": "Singapore",
            "address": "Home base",
            "business_hours_start": time(10, 0),
            "business_hours_end": time(19, 0),
            "store_type": StoreType.warehouse,
            "operational_status": StoreOperationalStatus.staging,
            "is_home_base": True,
            "is_temp_warehouse": True,
            "planned_open_date": date(2026, 5, 1),
            "notes": "Temporary warehouse before Jewel opens.",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    )

    parsed = _store_to_read(raw)

    assert parsed.store_type == StoreType.warehouse
    assert parsed.operational_status == StoreOperationalStatus.staging
    assert parsed.is_home_base is True
    assert parsed.is_temp_warehouse is True
    assert parsed.planned_open_date == date(2026, 5, 1)
    assert parsed.notes == "Temporary warehouse before Jewel opens."
