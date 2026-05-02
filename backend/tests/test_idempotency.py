"""Unit + integration tests for the ``Idempotency-Key`` cache used by
master-data multi-write endpoints (publish_prices_bulk, ingest/invoice/
commit, POST /products) and the ``/ai/recommend_prices`` rate limit.

The unit tier covers ``app.idempotency.guard`` directly (no FastAPI
plumbing). The integration tier drives the live router via httpx +
ASGITransport with auth + Firestore short-circuited.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import idempotency
from app.main import app
from app.routers import master_data


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


# ── integration: bulk publish endpoint replays cached response ───────────────


@pytest_asyncio.fixture
async def bulk_client(monkeypatch):
    actor = {
        "id": "test-user-id",
        "email": "turrell.craig.1971@gmail.com",
        "store_roles": [{"role": "owner", "store_id": "JEWEL-01"}],
    }
    app.dependency_overrides[master_data.require_publish_price_owner] = lambda: actor

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(master_data.require_publish_price_owner, None)


@pytest.mark.asyncio
async def test_bulk_publish_replays_response_for_duplicate_key(bulk_client, monkeypatch):
    """Same Idempotency-Key on a retry must return the original response and
    must not re-invoke ``_do_publish_price`` — that's the whole point of the
    header for the publish flow."""
    calls: list[str] = []

    def _fake(sku, req, *, actor, request):
        calls.append(sku)
        return {
            "ok": True,
            "sku": sku,
            "price_id": f"price-{sku}-{len(calls)}",
            "superseded_price_ids": [],
        }

    monkeypatch.setattr(master_data, "_do_publish_price", _fake)

    payload = {"items": [{"sku": "SKU-A", "retail_price": 12.5}]}
    headers = {"Idempotency-Key": "client-uuid-001"}

    r1 = await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk", json=payload, headers=headers
    )
    r2 = await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk", json=payload, headers=headers
    )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json() == r2.json()
    assert calls == ["SKU-A"]  # second request did not re-run the body


@pytest.mark.asyncio
async def test_bulk_publish_distinct_keys_run_independently(bulk_client, monkeypatch):
    calls: list[str] = []

    def _fake(sku, req, *, actor, request):
        calls.append(sku)
        return {"ok": True, "sku": sku, "price_id": "p", "superseded_price_ids": []}

    monkeypatch.setattr(master_data, "_do_publish_price", _fake)

    payload = {"items": [{"sku": "SKU-A", "retail_price": 12.5}]}
    await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk",
        json=payload,
        headers={"Idempotency-Key": "key-1"},
    )
    await bulk_client.post(
        "/api/master-data/products/publish_prices_bulk",
        json=payload,
        headers={"Idempotency-Key": "key-2"},
    )
    assert calls == ["SKU-A", "SKU-A"]


@pytest.mark.asyncio
async def test_recommend_prices_rate_limit_kicks_in(monkeypatch):
    """The 10/minute cap on ``/ai/recommend_prices`` must bite — DeepSeek
    bills per token and a stuck button could otherwise rack up cost."""
    from app.auth import dependencies as auth_deps

    actor = {
        "id": "rl-user",
        "email": "owner@example.com",
        "firebase_uid": "rl-uid",
        "store_roles": [{"role": "owner", "store_id": "JEWEL-01"}],
    }

    # Bypass Firebase + Firestore by short-circuiting both ends of the auth
    # chain: the role-check factory returns a fresh closure per import, so we
    # also override get_current_user (the role check pulls user off it).
    app.dependency_overrides[auth_deps.get_current_user] = lambda: actor
    app.dependency_overrides[auth_deps.get_token_claims] = lambda: {"uid": "rl-uid"}

    # Short-circuit the legacy AI call — we only care about the limiter here.
    legacy = master_data._legacy_master_data()
    monkeypatch.setattr(legacy, "recommend_prices", lambda req: {"recommendations": []})

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            statuses: list[int] = []
            for _ in range(12):
                r = await c.post(
                    "/api/master-data/ai/recommend_prices",
                    json={"target_skus": []},
                    headers={"Authorization": "Bearer fake-token"},
                )
                statuses.append(r.status_code)
            # The first 10 must succeed; at least one 429 must appear in the
            # tail. We don't assert exactly which call trips it because slowapi
            # counts in real time and ASGI scheduling could legitimately
            # reorder a sub-millisecond batch.
            assert statuses[:10].count(200) == 10, statuses
            assert 429 in statuses[10:], statuses
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_bulk_publish_without_header_runs_normally(bulk_client, monkeypatch):
    """No header → no caching, every request executes the body. Existing
    callers that haven't been updated must keep working unchanged."""
    calls: list[str] = []

    def _fake(sku, req, *, actor, request):
        calls.append(sku)
        return {"ok": True, "sku": sku, "price_id": "p", "superseded_price_ids": []}

    monkeypatch.setattr(master_data, "_do_publish_price", _fake)

    payload = {"items": [{"sku": "SKU-A", "retail_price": 12.5}]}
    await bulk_client.post("/api/master-data/products/publish_prices_bulk", json=payload)
    await bulk_client.post("/api/master-data/products/publish_prices_bulk", json=payload)
    assert calls == ["SKU-A", "SKU-A"]
