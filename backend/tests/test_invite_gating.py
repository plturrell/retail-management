"""Tests for the role-grant gates on ``POST /users/invite``.

Covers the pre-side-effect branches in :func:`app.routers.users.invite_user`
that decide whether the caller is allowed to grant the requested role. These
gates fire before any Firebase / Firestore / email I/O, so the tests drive
``invite_user`` directly with stubbed dependencies and assert on the raised
``HTTPException`` — no network or Firebase fakes required.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.auth.dependencies import RoleEnum
from app.routers import users as users_router


def _run(coro):
    return asyncio.run(coro)


def _caller(roles: list[tuple[str, str]]) -> dict:
    """Build a caller dict with the given (store_id, role_value) pairs."""
    return {
        "id": "caller-id",
        "email": "caller@example.com",
        "store_roles": [
            {"store_id": store_id, "role": RoleEnum(role_value)}
            for store_id, role_value in roles
        ],
    }


def _payload(role: str, store_ids: list | None = None) -> users_router.InviteRequest:
    return users_router.InviteRequest(
        email="newhire@example.com",
        full_name="New Hire",
        role=role,
        store_ids=store_ids or [],
    )


def _invoke(caller: dict, payload: users_router.InviteRequest) -> None:
    """Call ``invite_user`` with stubbed Request/db; expects an HTTPException."""
    _run(
        users_router.invite_user(
            request=None,  # unused on the early-exit paths
            payload=payload,
            caller=caller,
            db=None,
        )
    )


# ── unknown role ─────────────────────────────────────────────────────────────

def test_invite_rejects_unknown_role() -> None:
    caller = _caller([(str(uuid4()), "owner")])
    with pytest.raises(HTTPException) as exc:
        _invoke(caller, _payload("superuser"))
    assert exc.value.status_code == 400
    assert "Invalid role" in exc.value.detail


# ── manager / owner: owner-only ──────────────────────────────────────────────

def test_invite_manager_rejected_for_non_owner() -> None:
    caller = _caller([(str(uuid4()), "manager")])
    with pytest.raises(HTTPException) as exc:
        _invoke(caller, _payload("manager", [uuid4()]))
    assert exc.value.status_code == 403
    assert "owners can invite" in exc.value.detail.lower()


def test_invite_owner_rejected_for_non_owner() -> None:
    caller = _caller([(str(uuid4()), "manager")])
    with pytest.raises(HTTPException) as exc:
        _invoke(caller, _payload("owner", [uuid4()]))
    assert exc.value.status_code == 403


# ── system_admin: admin-only ─────────────────────────────────────────────────

def test_invite_system_admin_rejected_for_owner() -> None:
    """An owner without a system_admin assignment cannot grant system_admin."""
    caller = _caller([(str(uuid4()), "owner")])
    with pytest.raises(HTTPException) as exc:
        _invoke(caller, _payload("system_admin", [uuid4()]))
    assert exc.value.status_code == 403
    assert "system admin" in exc.value.detail.lower()


def test_invite_system_admin_rejected_for_manager() -> None:
    caller = _caller([(str(uuid4()), "manager")])
    with pytest.raises(HTTPException) as exc:
        _invoke(caller, _payload("system_admin", [uuid4()]))
    assert exc.value.status_code == 403


def test_invite_system_admin_requires_store_ids() -> None:
    """Even an admin caller can't grant system_admin without a store target —
    the role doc has to live somewhere for ``is_system_admin`` to find it."""
    caller = _caller([(str(uuid4()), "system_admin")])
    with pytest.raises(HTTPException) as exc:
        _invoke(caller, _payload("system_admin", []))
    assert exc.value.status_code == 400
    assert "store" in exc.value.detail.lower()


def test_invite_system_admin_passes_gates_for_admin_caller(monkeypatch) -> None:
    """An admin caller with stores supplied should pass the gates and proceed
    to the next stage (email validation here, since payload uses a normal
    address). We stop the call before Firebase is touched by giving an empty
    email — the email-validation 400 confirms the role gates passed."""
    caller = _caller([(str(uuid4()), "system_admin")])
    payload = users_router.InviteRequest(
        email="   ",  # blank → trips the email-validation 400 _after_ the role gates
        full_name="",
        role="system_admin",
        store_ids=[uuid4()],
    )
    with pytest.raises(HTTPException) as exc:
        _invoke(caller, payload)
    assert exc.value.status_code == 400
    assert "email" in exc.value.detail.lower()
