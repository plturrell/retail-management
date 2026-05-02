"""Tests for the publisher-allowlist gate on the master-data publish-price path.

Covers ``_assert_publish_allowed`` and the combined
``require_publish_price_owner`` dependency that enforces both the owner role
and the email allowlist before any price reaches Firestore.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers import master_data


# ── _assert_publish_allowed: pure allowlist check ────────────────────────────

def test_allowlist_accepts_named_publisher_email() -> None:
    actor = {"email": "turrell.craig.1971@gmail.com"}
    master_data._assert_publish_allowed(actor)  # no raise


def test_allowlist_is_case_insensitive() -> None:
    actor = {"email": "TURRELL.CRAIG.1971@Gmail.com"}
    master_data._assert_publish_allowed(actor)  # no raise


def test_allowlist_strips_surrounding_whitespace() -> None:
    actor = {"email": "  irina@victoriaenso.com  "}
    master_data._assert_publish_allowed(actor)  # no raise


def test_allowlist_rejects_non_publisher_email() -> None:
    actor = {"email": "intern@victoriaenso.com"}
    with pytest.raises(HTTPException) as exc:
        master_data._assert_publish_allowed(actor)
    assert exc.value.status_code == 403
    assert "publisher" in exc.value.detail.lower() or "owner" in exc.value.detail.lower()


def test_allowlist_rejects_missing_email() -> None:
    with pytest.raises(HTTPException) as exc:
        master_data._assert_publish_allowed({})
    assert exc.value.status_code == 403


def test_allowlist_rejects_none_email() -> None:
    with pytest.raises(HTTPException) as exc:
        master_data._assert_publish_allowed({"email": None})
    assert exc.value.status_code == 403


def test_allowlist_reads_email_off_object_attribute() -> None:
    class _Actor:
        email = "turrell.craig.1971@gmail.com"
    master_data._assert_publish_allowed(_Actor())  # no raise


def test_allowlist_picks_up_settings_changes(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "MASTER_DATA_PUBLISHER_EMAILS", ["new-owner@victoriaenso.com"]
    )
    # Default named publishers no longer pass.
    with pytest.raises(HTTPException) as exc:
        master_data._assert_publish_allowed({"email": "turrell.craig.1971@gmail.com"})
    assert exc.value.status_code == 403
    # The newly configured email does.
    master_data._assert_publish_allowed({"email": "new-owner@victoriaenso.com"})


# ── require_publish_price_owner: combined role + allowlist gate ──────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def _owner_actor(email: str) -> dict:
    return {
        "id": uuid4(),
        "firebase_uid": f"firebase-{uuid4()}",
        "email": email,
        "full_name": "Owner",
        "store_roles": [
            {"id": str(uuid4()), "store_id": uuid4(), "role": "owner"}
        ],
    }


def _staff_actor(email: str) -> dict:
    return {
        "id": uuid4(),
        "firebase_uid": f"firebase-{uuid4()}",
        "email": email,
        "full_name": "Staff",
        "store_roles": [
            {"id": str(uuid4()), "store_id": uuid4(), "role": "staff"}
        ],
    }


def test_require_publish_price_owner_passes_for_owner_on_allowlist() -> None:
    actor = _owner_actor("turrell.craig.1971@gmail.com")
    result = _run(master_data.require_publish_price_owner(actor=actor))
    assert result is actor


def test_require_publish_price_owner_rejects_owner_off_allowlist() -> None:
    actor = _owner_actor("intern@victoriaenso.com")
    with pytest.raises(HTTPException) as exc:
        _run(master_data.require_publish_price_owner(actor=actor))
    assert exc.value.status_code == 403


def test_require_publish_price_owner_rejects_allowlisted_non_owner() -> None:
    # Even if Craig somehow only had a staff role, the role gate must reject.
    actor = _staff_actor("turrell.craig.1971@gmail.com")
    with pytest.raises(HTTPException) as exc:
        _run(master_data.require_publish_price_owner(actor=actor))
    assert exc.value.status_code == 403
    assert "owner" in exc.value.detail.lower()


def test_require_publish_price_owner_rejects_user_with_no_store_roles() -> None:
    actor = {
        "id": uuid4(),
        "email": "turrell.craig.1971@gmail.com",
        "store_roles": [],
    }
    with pytest.raises(HTTPException) as exc:
        _run(master_data.require_publish_price_owner(actor=actor))
    assert exc.value.status_code == 403
