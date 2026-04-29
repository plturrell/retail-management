"""Tests for ``app.services.cag_config`` — Firestore-backed CAG config layer.

The fakes here also exercise ``app.services.cag_history`` because both
modules share the in-memory Firestore stub. Adding focused coverage for
``list_runs`` (server-side limit) and ``_error_key`` (collision-resistant
dedup) here avoids a new test file while keeping the fakes co-located.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services import cag_config, cag_history, cag_sftp


class FakeDocSnapshot:
    def __init__(self, data: dict[str, Any] | None):
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self._data) if self._data is not None else None


class FakeDocRef:
    def __init__(self, store: dict[str, dict[str, Any]], doc_id: str):
        self._store = store
        self._doc_id = doc_id

    def get(self) -> FakeDocSnapshot:
        return FakeDocSnapshot(self._store.get(self._doc_id))

    def set(self, data: dict[str, Any], merge: bool = False) -> None:
        if merge and self._doc_id in self._store:
            self._store[self._doc_id].update(data)
        else:
            self._store[self._doc_id] = dict(data)

    def delete(self) -> None:
        self._store.pop(self._doc_id, None)


class FakeQueryDocSnapshot:
    """Stand-in for the per-doc snapshot returned by ``query.stream()``."""

    def __init__(self, doc_id: str, data: dict[str, Any]):
        self.id = doc_id
        self._data = data
        self.exists = True

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class FakeQuery:
    """Minimal Firestore query that supports ``.order_by`` + ``.limit`` +
    ``.stream`` so we can exercise the ordered-then-limited path used by
    :func:`cag_history.list_runs` and :func:`cag_history.list_errors`."""

    def __init__(self, store: dict[str, dict[str, Any]], *, order_field: str | None = None,
                 descending: bool = False, limit_n: int | None = None):
        self._store = store
        self._order_field = order_field
        self._descending = descending
        self._limit = limit_n

    def order_by(self, field: str, direction: Any = None) -> "FakeQuery":
        # Match the google.cloud.firestore.Query.DESCENDING sentinel (string id).
        descending = bool(direction) and "DESC" in str(direction).upper()
        return FakeQuery(self._store, order_field=field, descending=descending, limit_n=self._limit)

    def limit(self, n: int) -> "FakeQuery":
        return FakeQuery(self._store, order_field=self._order_field,
                         descending=self._descending, limit_n=n)

    def where(self, field: str, op: str, value: Any) -> "FakeQuery":
        # Filter the store and return a new FakeQuery scoped to matches.
        if op != "==":
            raise NotImplementedError(op)
        filtered = {k: v for k, v in self._store.items() if v.get(field) == value}
        return FakeQuery(filtered, order_field=self._order_field,
                         descending=self._descending, limit_n=self._limit)

    def stream(self):
        rows = [(k, v) for k, v in self._store.items()]
        if self._order_field:
            rows.sort(key=lambda kv: kv[1].get(self._order_field) or "",
                      reverse=self._descending)
        if self._limit is not None:
            rows = rows[: self._limit]
        return [FakeQueryDocSnapshot(k, v) for k, v in rows]


class FakeCollection:
    def __init__(self, store: dict[str, dict[str, Any]]):
        self._store = store

    def document(self, doc_id: str) -> FakeDocRef:
        return FakeDocRef(self._store, doc_id)

    def order_by(self, field: str, direction: Any = None) -> FakeQuery:
        return FakeQuery(self._store).order_by(field, direction)

    def limit(self, n: int) -> FakeQuery:
        return FakeQuery(self._store).limit(n)

    def where(self, field: str, op: str, value: Any) -> FakeQuery:
        return FakeQuery(self._store).where(field, op, value)

    def stream(self):
        return FakeQuery(self._store).stream()


class FakeFirestore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {}

    def collection(self, name: str) -> FakeCollection:
        self.data.setdefault(name, {})
        return FakeCollection(self.data[name])


@pytest.fixture()
def fs() -> FakeFirestore:
    return FakeFirestore()


def test_load_config_returns_env_defaults_when_firestore_empty(fs):
    cfg = cag_config.load_config(fs)
    # Env defaults are blank in CI; spec port is 22, working folder is "Inbound/Working".
    assert cfg.port == 22
    assert cfg.inbound_working == "Inbound/Working"
    assert cfg.host == ""


def test_save_and_load_round_trip(fs):
    cag_config.save_config(
        fs,
        {
            "host": "sftp.cag.example",
            "port": 2222,
            "username": "tenant_200151",
            "password": "supersecret",
            "tenant_folder": "200151",
            "default_nec_store_id": "80001",
            "default_taxable": False,
        },
        updated_by="owner@victoriaenso.com",
    )
    cfg = cag_config.load_config(fs)
    assert cfg.host == "sftp.cag.example"
    assert cfg.port == 2222
    assert cfg.username == "tenant_200151"
    assert cfg.password == "supersecret"
    assert cfg.tenant_folder == "200151"
    assert cfg.default_nec_store_id == "80001"
    assert cfg.default_taxable is False
    assert cfg.updated_by == "owner@victoriaenso.com"
    assert cfg.updated_at  # ISO timestamp populated


def test_public_view_masks_secrets(fs):
    cag_config.save_config(fs, {"host": "h", "username": "u", "password": "p", "key_passphrase": "k"})
    pub = cag_config.load_config(fs).public_view()
    assert "password" not in pub
    assert "key_passphrase" not in pub
    assert pub["has_password"] is True
    assert pub["has_key_passphrase"] is True


def test_save_preserves_existing_secret_when_patch_field_empty(fs):
    cag_config.save_config(fs, {"host": "h", "username": "u", "password": "old-secret"})
    # Patch sends empty string for password — must keep "old-secret".
    cag_config.save_config(fs, {"host": "h2", "password": ""})
    cfg = cag_config.load_config(fs)
    assert cfg.host == "h2"
    assert cfg.password == "old-secret"


def test_save_overwrites_secret_when_non_empty(fs):
    cag_config.save_config(fs, {"password": "first"})
    cag_config.save_config(fs, {"password": "second"})
    assert cag_config.load_config(fs).password == "second"


def test_clear_wipes_overrides(fs):
    cag_config.save_config(fs, {"host": "h", "tenant_folder": "200151"})
    cag_config.clear_config(fs)
    cfg = cag_config.load_config(fs)
    assert cfg.host == ""
    assert cfg.tenant_folder == ""


def test_to_sftp_config_propagates_fields(fs):
    cag_config.save_config(
        fs,
        {
            "host": "sftp.cag.example",
            "port": 22,
            "username": "u",
            "password": "p",
            "tenant_folder": "200151",
            "inbound_working": "Inbound/Working",
        },
    )
    sftp_cfg = cag_config.load_config(fs).to_sftp_config()
    assert sftp_cfg.host == "sftp.cag.example"
    assert sftp_cfg.username == "u"
    assert sftp_cfg.tenant_folder == "200151"
    assert sftp_cfg.working_dir == "200151/Inbound/Working"


def test_scheduler_fields_round_trip(fs):
    cag_config.save_config(
        fs,
        {
            "scheduler_enabled": False,
            "scheduler_cron": "*/30 * * * *",
            "scheduler_default_tenant": "200151",
            "scheduler_default_store_id": "80001",
            "scheduler_default_taxable": True,
        },
    )
    cfg = cag_config.load_config(fs)
    assert cfg.scheduler_enabled is False
    assert cfg.scheduler_cron == "*/30 * * * *"
    assert cfg.scheduler_default_tenant == "200151"
    assert cfg.scheduler_default_store_id == "80001"
    assert cfg.scheduler_default_taxable is True


def test_record_scheduler_run_persists_on_existing_doc(fs):
    cag_config.save_config(fs, {"host": "h", "tenant_folder": "200151"})
    cag_config.record_scheduler_run(
        fs, status="success", message="OK", files=6, bytes_=1234, trigger="manual"
    )
    cfg = cag_config.load_config(fs)
    assert cfg.scheduler_last_run_status == "success"
    assert cfg.scheduler_last_run_files == 6
    assert cfg.scheduler_last_run_bytes == 1234
    assert cfg.scheduler_last_run_trigger == "manual"
    # Existing fields preserved (set merge=True semantics).
    assert cfg.host == "h"
    assert cfg.tenant_folder == "200151"


def test_record_scheduler_run_swallows_firestore_error():
    class BoomFs:
        def collection(self, name):
            raise RuntimeError("firestore down")
    # Must not raise — telemetry is best-effort.
    cag_config.record_scheduler_run(BoomFs(), status="failed", message="x")


def test_load_config_survives_firestore_exception():
    class BoomFs:
        def collection(self, name):
            class BoomColl:
                def document(self, _):
                    class BoomDoc:
                        def get(self_inner):
                            raise RuntimeError("transient")
                    return BoomDoc()
            return BoomColl()

    cfg = cag_config.load_config(BoomFs())
    # Falls back to env defaults — does not raise.
    assert cfg.port == 22



# ---------------------------------------------------------------------------
# host_fingerprint round-trip + propagation to SFTPConfig
# ---------------------------------------------------------------------------

def test_host_fingerprint_round_trip(fs):
    cag_config.save_config(fs, {"host": "h", "host_fingerprint": "SHA256:abcd1234"})
    cfg = cag_config.load_config(fs)
    assert cfg.host_fingerprint == "SHA256:abcd1234"
    assert cfg.to_sftp_config().host_fingerprint == "SHA256:abcd1234"


def test_host_fingerprint_clearable_via_empty_patch(fs):
    cag_config.save_config(fs, {"host_fingerprint": "SHA256:original"})
    # Empty string explicitly clears (this is non-secret, unlike password).
    cag_config.save_config(fs, {"host_fingerprint": ""})
    assert cag_config.load_config(fs).host_fingerprint == ""


# ---------------------------------------------------------------------------
# cag_history.list_runs / list_errors — server-side ordering + limit
# ---------------------------------------------------------------------------

def test_list_runs_uses_server_side_order_by_and_limit(fs):
    coll = fs.data.setdefault(cag_history.RUN_COLLECTION, {})
    # Seed 5 runs with monotonically increasing created_at.
    for i in range(5):
        coll[f"run-{i}"] = {
            "id": f"run-{i}",
            "created_at": f"2026-04-29T0{i}:00:00Z",
            "started_at": f"2026-04-29T0{i}:00:00Z",
            "ok": True,
        }
    rows = cag_history.list_runs(fs, limit=3)
    assert len(rows) == 3
    # Newest first.
    assert [r["id"] for r in rows] == ["run-4", "run-3", "run-2"]


def test_list_errors_uses_server_side_order_by_and_limit(fs):
    coll = fs.data.setdefault(cag_history.ERROR_COLLECTION, {})
    for i in range(4):
        coll[f"err-{i}"] = {
            "id": f"err-{i}",
            "synced_at": f"2026-04-29T0{i}:00:00Z",
            "message": f"diagnostic {i}",
            "line": 0,
        }
    rows = cag_history.list_errors(fs, limit=2)
    assert len(rows) == 2
    assert [r["id"] for r in rows] == ["err-3", "err-2"]


# ---------------------------------------------------------------------------
# cag_history._error_key — collision-resistant on (source_file, line=0)
# ---------------------------------------------------------------------------

def test_error_key_distinguishes_messages_on_same_file_and_line():
    a = cag_history._error_key("SKU.errorLog", 0, "CHILD_CATG_CODE not found")
    b = cag_history._error_key("SKU.errorLog", 0, "Mandatory fields are not filled")
    c = cag_history._error_key("SKU.errorLog", 0, "CHILD_CATG_CODE not found")
    assert a != b
    assert a == c  # same inputs → same key (idempotent on re-sync)


def test_sync_errors_persists_distinct_diagnostics_for_same_line(fs, monkeypatch):
    # Configure SFTP just enough for ``is_configured`` to pass.
    cag_config.save_config(fs, {"host": "h", "username": "u", "password": "p"})

    fake_entries = [
        cag_sftp.ErrorLogEntry("Failed", 0, "First unrecognised diagnostic", "X.errorLog"),
        cag_sftp.ErrorLogEntry("Failed", 0, "Second unrecognised diagnostic", "X.errorLog"),
    ]
    monkeypatch.setattr(cag_sftp, "fetch_error_logs", lambda config, limit=200: fake_entries)

    result = cag_history.sync_errors(fs)
    assert result == {"fetched": 2, "new": 2, "skipped": 0}
    # Both rows are persisted (not collapsed under one (file, line=0) key).
    coll = fs.data.get(cag_history.ERROR_COLLECTION) or {}
    messages = sorted(v["message"] for v in coll.values())
    assert messages == ["First unrecognised diagnostic", "Second unrecognised diagnostic"]


def test_sync_errors_dedups_on_repeat_sync(fs, monkeypatch):
    cag_config.save_config(fs, {"host": "h", "username": "u", "password": "p"})

    fake_entries = [
        cag_sftp.ErrorLogEntry("Failed", 1, "msg-a", "Y.errorLog"),
        cag_sftp.ErrorLogEntry("Failed", 2, "msg-b", "Y.errorLog"),
    ]
    monkeypatch.setattr(cag_sftp, "fetch_error_logs", lambda config, limit=200: fake_entries)

    first = cag_history.sync_errors(fs)
    second = cag_history.sync_errors(fs)
    assert first == {"fetched": 2, "new": 2, "skipped": 0}
    assert second == {"fetched": 2, "new": 0, "skipped": 2}
