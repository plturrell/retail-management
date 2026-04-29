"""Tests for ``app.services.cag_config`` — Firestore-backed CAG config layer."""
from __future__ import annotations

from typing import Any

import pytest

from app.services import cag_config


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


class FakeCollection:
    def __init__(self, store: dict[str, dict[str, Any]]):
        self._store = store

    def document(self, doc_id: str) -> FakeDocRef:
        return FakeDocRef(self._store, doc_id)


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
