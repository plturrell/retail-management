from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Iterator
from uuid import UUID, uuid4

from app.auth.dependencies import get_current_user
from app.firestore_helpers import create_document
from app.main import app
from tests.firestore_seed import mirror_order, mirror_role, mirror_store, mirror_time_entry, mirror_user


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class StoreScenario:
    store_id: UUID
    owner_id: UUID
    employee_id: UUID


def seed_store_scenario(
    *,
    store_code: str = "JEWEL-01",
    store_name: str = "Jewel",
    store_location: str = "Jewel Changi Airport",
    store_address: str = "78 Airport Blvd",
    owner_name: str = "Owner User",
    employee_name: str = "Test User",
) -> StoreScenario:
    store_id = uuid4()
    owner_id = uuid4()
    employee_id = uuid4()
    now = _now()

    mirror_store(
        SimpleNamespace(
            id=store_id,
            store_code=store_code,
            name=store_name,
            location=store_location,
            address=store_address,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )

    mirror_user(
        SimpleNamespace(
            id=owner_id,
            firebase_uid=f"firebase-{owner_id}",
            email="owner@example.com",
            full_name=owner_name,
            phone=None,
            created_at=now,
            updated_at=now,
        )
    )
    mirror_user(
        SimpleNamespace(
            id=employee_id,
            firebase_uid=f"firebase-{employee_id}",
            email="employee@example.com",
            full_name=employee_name,
            phone=None,
            created_at=now,
            updated_at=now,
        )
    )
    mirror_role(
        SimpleNamespace(
            id=uuid4(),
            user_id=owner_id,
            store_id=store_id,
            role="owner",
            created_at=now,
        )
    )

    create_document(
        f"stores/{store_id}/employees",
        {
            "id": str(employee_id),
            "user_id": str(employee_id),
            "created_at": now,
            "updated_at": now,
        },
        doc_id=str(employee_id),
    )

    return StoreScenario(store_id=store_id, owner_id=owner_id, employee_id=employee_id)


def seed_employee_profile(
    *,
    user_id: UUID,
    basic_salary: str,
    commission_rate: str | None = None,
    hourly_rate: str | None = None,
    nationality: str = "foreigner",
) -> None:
    now = _now()
    payload = {
        "id": str(user_id),
        "user_id": str(user_id),
        "date_of_birth": "1995-06-15",
        "nationality": nationality,
        "basic_salary": basic_salary,
        "hourly_rate": hourly_rate,
        "commission_rate": commission_rate,
        "bank_account": None,
        "bank_name": "OCBC",
        "cpf_account_number": None,
        "start_date": "2024-01-01",
        "end_date": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    create_document("employee-profiles", payload, doc_id=str(user_id))


def seed_completed_order(
    *,
    store_id: UUID,
    salesperson_id: UUID,
    grand_total: float,
    order_date: datetime,
) -> None:
    mirror_order(
        store_id=store_id,
        salesperson_id=salesperson_id,
        staff_id=salesperson_id,
        order_date=order_date,
        grand_total=grand_total,
        status="completed",
        source="manual",
    )


def seed_approved_time_entries(
    *,
    store_id: UUID,
    user_id: UUID,
    entries: list[tuple[datetime, datetime, int]],
) -> None:
    for clock_in, clock_out, break_minutes in entries:
        mirror_time_entry(
            SimpleNamespace(
                id=uuid4(),
                user_id=user_id,
                store_id=store_id,
                clock_in=clock_in,
                clock_out=clock_out,
                break_minutes=break_minutes,
                status="approved",
                approved_by=None,
                created_at=_now(),
                updated_at=_now(),
            ),
            user_name="Test User",
        )


@contextmanager
def override_owner_user(*, owner_id: UUID, store_id: UUID, full_name: str = "Owner User") -> Iterator[None]:
    previous_override = app.dependency_overrides.get(get_current_user)

    async def _override_user():
        return {
            "id": owner_id,
            "firebase_uid": f"firebase-{owner_id}",
            "email": "owner@example.com",
            "full_name": full_name,
            "phone": None,
            "store_roles": [
                {
                    "id": str(uuid4()),
                    "store_id": store_id,
                    "role": "owner",
                }
            ],
        }

    app.dependency_overrides[get_current_user] = _override_user
    try:
        yield
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous_override
