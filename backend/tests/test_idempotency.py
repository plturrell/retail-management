"""Unit tests for the ``Idempotency-Key`` cache used by master-data
multi-write endpoints (publish_prices_bulk, ingest/invoice/commit,
POST /products).

Covers ``app.idempotency.guard`` directly (no FastAPI plumbing). The
companion integration tests against the live router live alongside the
router wraps and land in the same commit as ``backend/app/routers/master_data.py``;
a temporary holding copy sits in ``_pending_idempotency_integration.py.txt``
until then.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import idempotency


# ── unit tests against guard() ───────────────────────────────────────────────


def _fake_request(headers: dict[str, str] | None = None):
    return SimpleNamespace(headers=headers or {})


@pytest.fixture(autouse=True)
def _clear_cache():
    idempotency._reset_for_tests()
    yield
    idempotency._reset_for_tests()


def test_guard_yields_none_when_header_missing():
    actor = {"email": "owner@example.com"}
    with idempotency.guard(_fake_request(), "scope", actor) as g:
        assert g is None


def test_guard_caches_and_replays_response():
    actor = {"email": "owner@example.com"}
    req = _fake_request({"Idempotency-Key": "abc-123"})

    runs = 0
    with idempotency.guard(req, "scope", actor) as g:
        assert g is not None
        assert g.cached is None
        runs += 1
        g.store({"ok": True, "n": 1})

    with idempotency.guard(req, "scope", actor) as g:
        assert g is not None
        assert g.cached == {"ok": True, "n": 1}
    # Second call must NOT have re-run the body — caller would skip work.
    assert runs == 1


def test_guard_isolates_by_actor():
    """Two users sending the same key must each get a fresh guard."""
    a = {"email": "a@example.com"}
    b = {"email": "b@example.com"}
    req = _fake_request({"Idempotency-Key": "shared-key"})

    with idempotency.guard(req, "scope", a) as g:
        g.store({"who": "a"})
    with idempotency.guard(req, "scope", b) as g:
        assert g.cached is None  # different actor → no replay


def test_guard_isolates_by_scope():
    actor = {"email": "owner@example.com"}
    req = _fake_request({"Idempotency-Key": "k"})

    with idempotency.guard(req, "scope-a", actor) as g:
        g.store({"v": "a"})
    with idempotency.guard(req, "scope-b", actor) as g:
        assert g.cached is None


def test_guard_rejects_overlong_key():
    actor = {"email": "owner@example.com"}
    req = _fake_request({"Idempotency-Key": "x" * 5000})

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        with idempotency.guard(req, "scope", actor):
            pass
    assert exc.value.status_code == 400


def test_guard_treats_blank_header_as_absent():
    actor = {"email": "owner@example.com"}
    req = _fake_request({"Idempotency-Key": "   "})
    with idempotency.guard(req, "scope", actor) as g:
        assert g is None



