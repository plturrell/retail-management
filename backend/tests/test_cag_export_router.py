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
