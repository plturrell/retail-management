"""Router tests for the CAG export push endpoints.

The SFTP transport, bundle build, and Firestore client are all mocked. We're
asserting the routing layer: that ``/push/scheduled`` is gated by the
scheduler OIDC dep, that defaults resolve in the intended order, and that
body overrides win.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.routers import cag_export
from app.services import cag_sftp


class _FakeBundle:
    files = []
    counts = {"sku": 0}


class _FakeUpload:
    files_uploaded = ["SKU_10001_20260429000000.txt"]
    bytes_uploaded = 42
    started_at = datetime(2026, 4, 29, 0, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 4, 29, 0, 0, 1, tzinfo=timezone.utc)
    errors = []


@pytest_asyncio.fixture
async def client_no_auth(monkeypatch):
    """ASGI client that does NOT install the scheduler OIDC override —
    used to assert 401 on the gated endpoint."""
    monkeypatch.setattr(settings, "CAG_SCHEDULER_SA_EMAIL", "cag-scheduler@victoriaenso.iam.gserviceaccount.com")
    monkeypatch.setattr(settings, "CAG_SCHEDULER_AUDIENCE", "https://retailsg-api-victoriaenso.run.app")
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_TENANT", "victoriaenso")
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_STORE_ID", "80001")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_with_oidc(monkeypatch):
    """ASGI client that overrides the scheduler OIDC dep + Firestore + SFTP
    so the handler runs end-to-end without external services."""
    monkeypatch.setattr(settings, "CAG_SCHEDULER_SA_EMAIL", "cag-scheduler@victoriaenso.iam.gserviceaccount.com")
    monkeypatch.setattr(settings, "CAG_SCHEDULER_AUDIENCE", "https://retailsg-api-victoriaenso.run.app")
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_TENANT", "victoriaenso")
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_STORE_ID", "80001")

    from app.auth.dependencies import require_scheduler_oidc
    from app.firestore import get_firestore_db

    captured: dict = {}

    def _fake_load_config(fs_db):
        class _Cfg:
            scheduler_default_tenant = ""
            scheduler_default_store_id = ""
            scheduler_default_taxable = False
            tenant_folder = ""
            default_nec_store_id = ""

            def to_sftp_config(self):
                return cag_sftp.SFTPConfig(host="h", port=22, username="u", password="p")
        return _Cfg()

    def _fake_build_bundle(fs_db, **kwargs):
        captured["build_kwargs"] = kwargs
        return _FakeBundle()

    def _fake_upload(files, *, config):
        return _FakeUpload()

    def _fake_record(fs_db, **kwargs):
        captured["telemetry"] = kwargs

    monkeypatch.setattr(cag_export.cag_config, "load_config", _fake_load_config)
    monkeypatch.setattr(cag_export.cag_config, "record_scheduler_run", _fake_record)
    monkeypatch.setattr(cag_export, "_build_bundle", _fake_build_bundle)
    monkeypatch.setattr(cag_export.cag_sftp, "upload_files", _fake_upload)

    app.dependency_overrides[require_scheduler_oidc] = lambda: {"email": "cag-scheduler@victoriaenso.iam.gserviceaccount.com"}
    app.dependency_overrides[get_firestore_db] = lambda: object()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, captured

    app.dependency_overrides.pop(require_scheduler_oidc, None)
    app.dependency_overrides.pop(get_firestore_db, None)


@pytest.mark.asyncio
async def test_scheduled_push_rejects_unauthenticated(client_no_auth):
    resp = await client_no_auth.post("/api/cag/export/push/scheduled", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_scheduled_push_uses_settings_defaults(client_with_oidc):
    client, captured = client_with_oidc
    resp = await client.post("/api/cag/export/push/scheduled", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["files_uploaded"] == ["SKU_10001_20260429000000.txt"]
    # _build_bundle should have been called with the settings defaults.
    assert captured["build_kwargs"]["tenant_code"] == "victoriaenso"
    assert captured["build_kwargs"]["nec_store_id"] == "80001"
    assert captured["build_kwargs"]["taxable"] is False


@pytest.mark.asyncio
async def test_scheduled_push_body_overrides_win(client_with_oidc):
    client, captured = client_with_oidc
    resp = await client.post(
        "/api/cag/export/push/scheduled",
        json={"tenant_code": "other", "nec_store_id": "80002", "taxable": True},
    )
    assert resp.status_code == 200, resp.text
    assert captured["build_kwargs"]["tenant_code"] == "other"
    assert captured["build_kwargs"]["nec_store_id"] == "80002"
    assert captured["build_kwargs"]["taxable"] is True


@pytest.mark.asyncio
async def test_scheduled_push_500s_when_misconfigured(client_with_oidc, monkeypatch):
    client, _ = client_with_oidc
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_TENANT", "")
    resp = await client.post("/api/cag/export/push/scheduled", json={})
    assert resp.status_code == 500
    assert "scheduler_default_tenant" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scheduled_push_uses_shared_cag_config_fallbacks(client_with_oidc, monkeypatch):
    client, captured = client_with_oidc
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_TENANT", "")
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_STORE_ID", "")

    def _fake_load_config(fs_db):
        class _Cfg:
            scheduler_default_tenant = ""
            scheduler_default_store_id = ""
            scheduler_default_taxable = True
            tenant_folder = "200151"
            default_nec_store_id = "80001"

            def to_sftp_config(self):
                return cag_sftp.SFTPConfig(host="h", port=22, username="u", password="p")
        return _Cfg()

    monkeypatch.setattr(cag_export.cag_config, "load_config", _fake_load_config)
    resp = await client.post("/api/cag/export/push/scheduled", json={})
    assert resp.status_code == 200, resp.text
    assert captured["build_kwargs"]["tenant_code"] == "200151"
    assert captured["build_kwargs"]["nec_store_id"] == "80001"
    assert captured["build_kwargs"]["taxable"] is True


@pytest.mark.asyncio
async def test_scheduled_push_rejects_non_nec_store_id(client_with_oidc, monkeypatch):
    client, _ = client_with_oidc
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_STORE_ID", "JEWEL-01")
    resp = await client.post("/api/cag/export/push/scheduled", json={})
    assert resp.status_code == 500
    assert "5-digit" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scheduled_push_records_success_telemetry(client_with_oidc):
    client, captured = client_with_oidc
    resp = await client.post("/api/cag/export/push/scheduled", json={})
    assert resp.status_code == 200
    tel = captured["telemetry"]
    assert tel["status"] == "success"
    assert tel["trigger"] == "scheduler"
    assert tel["files"] == 1
    assert tel["bytes_"] == 42


@pytest_asyncio.fixture
async def client_as_owner(monkeypatch):
    """Owner-authenticated client for the on-demand /push/test endpoint."""
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_TENANT", "victoriaenso")
    monkeypatch.setattr(settings, "CAG_SCHEDULED_PUSH_DEFAULT_STORE_ID", "80001")

    from app.auth.dependencies import get_current_user
    from app.firestore import get_firestore_db

    captured: dict = {}

    def _fake_load_config(fs_db):
        class _Cfg:
            scheduler_default_tenant = ""
            scheduler_default_store_id = ""
            scheduler_default_taxable = False
            tenant_folder = ""
            default_nec_store_id = ""

            def to_sftp_config(self):
                return cag_sftp.SFTPConfig(host="h", port=22, username="u", password="p")
        return _Cfg()

    def _fake_build_bundle(fs_db, **kwargs):
        captured["build_kwargs"] = kwargs
        return _FakeBundle()

    def _fake_upload(files, *, config):
        return _FakeUpload()

    def _fake_record(fs_db, **kwargs):
        captured["telemetry"] = kwargs

    monkeypatch.setattr(cag_export.cag_config, "load_config", _fake_load_config)
    monkeypatch.setattr(cag_export.cag_config, "record_scheduler_run", _fake_record)
    monkeypatch.setattr(cag_export, "_build_bundle", _fake_build_bundle)
    monkeypatch.setattr(cag_export.cag_sftp, "upload_files", _fake_upload)

    async def _owner_user():
        return {
            "id": "owner-id",
            "firebase_uid": "owner-uid",
            "email": "owner@victoriaenso.com",
            "store_roles": [{"role": "owner", "store_id": "JEWEL-01"}],
        }

    app.dependency_overrides[get_current_user] = _owner_user
    app.dependency_overrides[get_firestore_db] = lambda: object()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, captured

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_firestore_db, None)


@pytest.mark.asyncio
async def test_push_test_endpoint_runs_with_owner_auth(client_as_owner):
    client, captured = client_as_owner
    resp = await client.post("/api/cag/export/push/test", json={})
    assert resp.status_code == 200, resp.text
    assert captured["build_kwargs"]["tenant_code"] == "victoriaenso"
    assert captured["telemetry"]["trigger"] == "manual"
    assert captured["telemetry"]["status"] == "success"


@pytest.mark.asyncio
async def test_push_test_endpoint_body_overrides_win(client_as_owner):
    client, captured = client_as_owner
    resp = await client.post(
        "/api/cag/export/push/test",
        json={"tenant_code": "ad-hoc", "nec_store_id": "80099", "taxable": True},
    )
    assert resp.status_code == 200
    assert captured["build_kwargs"]["tenant_code"] == "ad-hoc"
    assert captured["build_kwargs"]["nec_store_id"] == "80099"
    assert captured["build_kwargs"]["taxable"] is True


@pytest.mark.asyncio
async def test_push_test_endpoint_rejects_unauthenticated(client_no_auth):
    resp = await client_no_auth.post("/api/cag/export/push/test", json={})
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# _resolve_store_nec_fields — uses an indexed equality query, not a scan
# ---------------------------------------------------------------------------

class _FakeStream:
    """Iterable returned from ``query.stream()``."""

    def __init__(self, snaps):
        self._snaps = snaps

    def __iter__(self):
        return iter(self._snaps)


class _FakeSnap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeStoresQuery:
    """Records ``where``/``limit`` calls so the test can assert the targeted
    lookup is used instead of a collection-wide ``stream()``."""

    def __init__(self, docs, calls):
        self._docs = docs
        self._calls = calls
        self._filtered = list(docs)
        self._limit = None

    def where(self, field, op, value):
        self._calls.append(("where", field, op, value))
        assert op == "=="
        self._filtered = [d for d in self._docs if d.get(field) == value]
        return self

    def limit(self, n):
        self._calls.append(("limit", n))
        self._limit = n
        return self

    def stream(self):
        self._calls.append(("stream",))
        rows = self._filtered if self._limit is None else self._filtered[: self._limit]
        return _FakeStream([_FakeSnap(d) for d in rows])


class _FakeStoresFs:
    def __init__(self, docs):
        self._docs = docs
        self.calls: list = []

    def collection(self, name):
        assert name == "stores"
        return _FakeStoresQuery(self._docs, self.calls)


def test_resolve_store_nec_fields_uses_indexed_where_query():
    docs = [
        {"store_code": "JEWEL-01", "nec_store_id": "80001", "nec_taxable": True,  "nec_tenant_code": "200151"},
        {"store_code": "JEWEL-02", "nec_store_id": "80002", "nec_taxable": False, "nec_tenant_code": "200151"},
        {"store_code": "JEWEL-03", "nec_store_id": "80003", "nec_taxable": True,  "nec_tenant_code": "200151"},
    ]
    fs = _FakeStoresFs(docs)
    out = cag_export._resolve_store_nec_fields(fs, "JEWEL-02")
    assert out == {"nec_store_id": "80002", "nec_taxable": False, "nec_tenant_code": "200151"}
    # The lookup must be performed via an equality query + limit, NOT a full scan.
    assert ("where", "store_code", "==", "JEWEL-02") in fs.calls
    assert ("limit", 1) in fs.calls
    # ``where`` must precede ``stream`` so the server filters before returning rows.
    where_idx = next(i for i, c in enumerate(fs.calls) if c[0] == "where")
    stream_idx = next(i for i, c in enumerate(fs.calls) if c[0] == "stream")
    assert where_idx < stream_idx


def test_resolve_store_nec_fields_returns_empty_when_no_match():
    fs = _FakeStoresFs([{"store_code": "OTHER", "nec_store_id": "99999"}])
    assert cag_export._resolve_store_nec_fields(fs, "JEWEL-01") == {}


def test_resolve_store_nec_fields_empty_inputs_short_circuit():
    # No fs_db → no query attempted.
    assert cag_export._resolve_store_nec_fields(None, "JEWEL-01") == {}
    # No store_code → no query attempted (fs.calls stays empty).
    fs = _FakeStoresFs([{"store_code": "JEWEL-01"}])
    assert cag_export._resolve_store_nec_fields(fs, None) == {}
    assert fs.calls == []


@pytest.mark.asyncio
async def test_push_test_endpoint_records_sftp_configuration_failure(client_as_owner, monkeypatch):
    client, captured = client_as_owner

    def _raise_upload(files, *, config):
        raise cag_sftp.SFTPConfigurationError("missing key")

    def _fake_history(fs_db, **kwargs):
        captured["history"] = kwargs

    monkeypatch.setattr(cag_export.cag_sftp, "upload_files", _raise_upload)
    monkeypatch.setattr(cag_export.cag_history, "record_run", _fake_history)

    resp = await client.post("/api/cag/export/push/test", json={})
    assert resp.status_code == 503
    assert "missing key" in resp.json()["detail"]
    assert captured["history"]["errors"] == ["SFTPConfigurationError: missing key"]
    assert captured["history"]["files_uploaded"] == []
    assert captured["history"]["trigger_kind"] == "manual"
    assert captured["telemetry"]["status"] == "failed"
    assert captured["telemetry"]["trigger"] == "manual"


# ---------------------------------------------------------------------------
# Per-store NEC mapping validation (StoreCreate / StoreUpdate)
#
# Invalid values would otherwise propagate into the security-critical CAG
# export — bad ``nec_store_id`` builds malformed filenames and bad
# ``nec_tenant_code`` becomes a path segment under ``Inbound/Working/<tenant>``.
# These tests assert the schemas reject anything that would not survive the
# runtime gate in ``cag_export._validate_nec_store_id``.
# ---------------------------------------------------------------------------


class _StoreFixtureMixin:
    @staticmethod
    def _base_payload(**overrides):
        from datetime import time

        payload = {
            "store_code": "JEWEL-01",
            "name": "Jewel",
            "location": "Changi",
            "address": "78 Airport Boulevard",
            "business_hours_start": time(9, 0),
            "business_hours_end": time(22, 0),
        }
        payload.update(overrides)
        return payload


class TestStoreCreateNecValidation(_StoreFixtureMixin):
    @pytest.mark.parametrize("value", ["80001", " 80001 ", "00000"])
    def test_accepts_five_digit_store_id(self, value):
        from app.schemas.store import StoreCreate

        store = StoreCreate(**self._base_payload(nec_store_id=value))
        assert store.nec_store_id == value.strip()

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_blank_store_id_normalizes_to_none(self, value):
        from app.schemas.store import StoreCreate

        store = StoreCreate(**self._base_payload(nec_store_id=value))
        assert store.nec_store_id is None

    @pytest.mark.parametrize(
        "value",
        ["abc", "1234", "123456", "abcde", "12 45", "../80", "8000A", "8000\u3000"],
    )
    def test_rejects_malformed_store_id(self, value):
        from pydantic import ValidationError

        from app.schemas.store import StoreCreate

        with pytest.raises(ValidationError) as exc:
            StoreCreate(**self._base_payload(nec_store_id=value))
        assert "5 ASCII digits" in str(exc.value)

    @pytest.mark.parametrize("value", ["200151", "2001516", " 200151 "])
    def test_accepts_six_or_seven_digit_tenant_code(self, value):
        from app.schemas.store import StoreCreate

        store = StoreCreate(**self._base_payload(nec_tenant_code=value))
        assert store.nec_tenant_code == value.strip()

    @pytest.mark.parametrize(
        "value",
        ["12345", "12345678", "20015X", "../etc", "200 51"],
    )
    def test_rejects_malformed_tenant_code(self, value):
        from pydantic import ValidationError

        from app.schemas.store import StoreCreate

        with pytest.raises(ValidationError) as exc:
            StoreCreate(**self._base_payload(nec_tenant_code=value))
        assert "Customer No." in str(exc.value)


class TestStoreUpdateNecValidation:
    @pytest.mark.parametrize("value", ["abcde", "1234", "../80"])
    def test_patch_rejects_bad_store_id(self, value):
        from pydantic import ValidationError

        from app.schemas.store import StoreUpdate

        with pytest.raises(ValidationError):
            StoreUpdate(nec_store_id=value)

    @pytest.mark.parametrize("value", ["12345", "../etc", "20015X"])
    def test_patch_rejects_bad_tenant_code(self, value):
        from pydantic import ValidationError

        from app.schemas.store import StoreUpdate

        with pytest.raises(ValidationError):
            StoreUpdate(nec_tenant_code=value)

    def test_patch_accepts_clean_values_and_strips_whitespace(self):
        from app.schemas.store import StoreUpdate

        patch = StoreUpdate(nec_store_id=" 80001 ", nec_tenant_code=" 200151 ")
        assert patch.nec_store_id == "80001"
        assert patch.nec_tenant_code == "200151"

    def test_patch_treats_empty_string_as_clear(self):
        from app.schemas.store import StoreUpdate

        patch = StoreUpdate(nec_store_id="", nec_tenant_code="")
        assert patch.nec_store_id is None
        assert patch.nec_tenant_code is None

    def test_storeread_tolerates_legacy_persisted_values(self):
        # Pre-existing docs may contain malformed values written before the
        # validators were added; reads must surface them so the operator
        # can fix them via PATCH rather than 500-ing the GET.
        from datetime import datetime as _dt
        from datetime import time, timezone
        from uuid import uuid4

        from app.schemas.store import StoreRead

        read = StoreRead(
            id=uuid4(),
            store_code="LEGACY-01",
            name="Legacy",
            location="x",
            address="y",
            business_hours_start=time(9, 0),
            business_hours_end=time(22, 0),
            nec_store_id="1234",  # 4 digits — illegal for new writes
            nec_tenant_code="abc",  # non-digit — illegal for new writes
            created_at=_dt.now(timezone.utc),
        )
        assert read.nec_store_id == "1234"
        assert read.nec_tenant_code == "abc"
