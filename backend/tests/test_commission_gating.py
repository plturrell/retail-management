"""Tests for the role-gates and single-active-rule enforcement on the
``/api/stores/{store_id}/commission-rules`` endpoints.

The role-gate branches in :mod:`app.routers.payroll` fire before any
Firestore I/O via :func:`ensure_store_role` (which reads only the user dict),
so those tests drive the handlers directly with stubbed dependencies and
assert on the raised ``HTTPException`` — no Firestore fakes required.

The single-active-rule branch sits between the role gate and the write call;
it consults ``query_collection`` for an existing active rule. Those tests
monkeypatch the helpers imported into the ``payroll`` module namespace.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.auth.dependencies import RoleEnum
from app.routers import payroll as payroll_router
from app.schemas.payroll import (
    CommissionRuleCreate,
    CommissionRuleUpdate,
    CommissionTier,
)


def _run(coro):
    return asyncio.run(coro)


def _user(store_id, role: str) -> dict:
    """Build a caller dict with one (store_id, role) assignment."""
    return {
        "id": "caller-id",
        "email": "caller@example.com",
        "firebase_uid": "caller-uid",
        "store_roles": [
            {"store_id": store_id, "role": RoleEnum(role)},
        ],
    }


def _create_payload(*, is_active: bool = True) -> CommissionRuleCreate:
    return CommissionRuleCreate(
        name="Default",
        tiers=[CommissionTier(min=0, max=None, rate="0.05")],
        is_active=is_active,
    )


def _update_payload(**fields) -> CommissionRuleUpdate:
    return CommissionRuleUpdate(**fields)


# ── role gates (no DB stubs needed) ──────────────────────────────────────────

@pytest.mark.parametrize("role", ["staff", "manager"])
def test_create_rule_rejected_below_owner(role: str) -> None:
    store_id = uuid4()
    caller = _user(store_id, role)
    with pytest.raises(HTTPException) as exc:
        _run(payroll_router.create_commission_rule(
            store_id=store_id,
            payload=_create_payload(),
            request=None,
            user=caller,
            db=None,
        ))
    assert exc.value.status_code == 403
    assert "owner" in exc.value.detail.lower()


@pytest.mark.parametrize("role", ["staff", "manager"])
def test_update_rule_rejected_below_owner(role: str) -> None:
    store_id = uuid4()
    caller = _user(store_id, role)
    with pytest.raises(HTTPException) as exc:
        _run(payroll_router.update_commission_rule(
            store_id=store_id,
            rule_id=uuid4(),
            payload=_update_payload(name="x"),
            request=None,
            user=caller,
            db=None,
        ))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["staff", "manager"])
def test_delete_rule_rejected_below_owner(role: str) -> None:
    store_id = uuid4()
    caller = _user(store_id, role)
    with pytest.raises(HTTPException) as exc:
        _run(payroll_router.delete_commission_rule(
            store_id=store_id,
            rule_id=uuid4(),
            request=None,
            user=caller,
            db=None,
        ))
    assert exc.value.status_code == 403


def test_create_rule_rejected_for_non_member() -> None:
    """Caller has roles on a *different* store — must be denied."""
    target_store = uuid4()
    other_store = uuid4()
    caller = _user(other_store, "owner")
    with pytest.raises(HTTPException) as exc:
        _run(payroll_router.create_commission_rule(
            store_id=target_store,
            payload=_create_payload(),
            request=None,
            user=caller,
            db=None,
        ))
    assert exc.value.status_code == 403


# ── single-active-rule enforcement ───────────────────────────────────────────

def test_create_active_rule_conflicts_when_another_active_exists(monkeypatch) -> None:
    store_id = uuid4()
    caller = _user(store_id, "owner")

    # An active rule already exists for this store.
    monkeypatch.setattr(
        payroll_router,
        "query_collection",
        lambda col, filters=(): [{"id": str(uuid4()), "is_active": True}],
    )

    with pytest.raises(HTTPException) as exc:
        _run(payroll_router.create_commission_rule(
            store_id=store_id,
            payload=_create_payload(is_active=True),
            request=None,
            user=caller,
            db=None,
        ))
    assert exc.value.status_code == 409
    assert "already active" in exc.value.detail.lower()


def test_create_inactive_rule_allowed_when_another_active_exists(monkeypatch) -> None:
    """A new *inactive* rule should pass the uniqueness check even if another
    rule is active — only transitions *into* the active state are blocked."""
    store_id = uuid4()
    caller = _user(store_id, "owner")

    # Active rule exists, but new payload is inactive — uniqueness check
    # should be skipped, so query_collection should never even be called.
    def _explode(*_a, **_kw):
        raise AssertionError("query_collection must not be consulted for inactive creates")
    monkeypatch.setattr(payroll_router, "query_collection", _explode)
    monkeypatch.setattr(
        payroll_router,
        "create_document",
        lambda col, data, doc_id=None: {**data, "id": doc_id or "new-id"},
    )
    monkeypatch.setattr(payroll_router, "log_event", lambda *a, **kw: None)

    resp = _run(payroll_router.create_commission_rule(
        store_id=store_id,
        payload=_create_payload(is_active=False),
        request=None,
        user=caller,
        db=None,
    ))
    assert resp.data.is_active is False


def test_update_activation_conflicts_when_another_active_exists(monkeypatch) -> None:
    """Flipping an inactive rule to active while another active rule exists
    must be blocked with 409."""
    store_id = uuid4()
    rule_id = uuid4()
    caller = _user(store_id, "owner")

    monkeypatch.setattr(
        payroll_router,
        "get_document",
        lambda col, doc_id: {
            "id": doc_id,
            "store_id": str(store_id),
            "name": "Default",
            "tiers": [{"min": "0", "max": None, "rate": "0.05"}],
            "is_active": False,
        },
    )
    monkeypatch.setattr(
        payroll_router,
        "query_collection",
        lambda col, filters=(): [{"id": str(uuid4()), "is_active": True}],
    )

    with pytest.raises(HTTPException) as exc:
        _run(payroll_router.update_commission_rule(
            store_id=store_id,
            rule_id=rule_id,
            payload=_update_payload(is_active=True),
            request=None,
            user=caller,
            db=None,
        ))
    assert exc.value.status_code == 409


def test_update_already_active_rule_allowed_despite_other_actives(monkeypatch) -> None:
    """Editing a rule that is *already* active doesn't trip the uniqueness
    check — needed so existing multi-rule stores can still be maintained."""
    store_id = uuid4()
    rule_id = uuid4()
    caller = _user(store_id, "owner")

    monkeypatch.setattr(
        payroll_router,
        "get_document",
        lambda col, doc_id: {
            "id": doc_id,
            "store_id": str(store_id),
            "name": "Default",
            "tiers": [{"min": "0", "max": None, "rate": "0.05"}],
            "is_active": True,
        },
    )

    def _explode(*_a, **_kw):
        raise AssertionError("query_collection must not be consulted for non-activating edits")
    monkeypatch.setattr(payroll_router, "query_collection", _explode)
    monkeypatch.setattr(
        payroll_router,
        "update_document",
        lambda col, doc_id, updates: {
            "id": doc_id,
            "store_id": str(store_id),
            "name": updates.get("name", "Default"),
            "tiers": [{"min": "0", "max": None, "rate": "0.05"}],
            "is_active": True,
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        },
    )
    monkeypatch.setattr(payroll_router, "log_event", lambda *a, **kw: None)

    resp = _run(payroll_router.update_commission_rule(
        store_id=store_id,
        rule_id=rule_id,
        payload=_update_payload(name="Renamed"),
        request=None,
        user=caller,
        db=None,
    ))
    assert resp.data.name == "Renamed"
