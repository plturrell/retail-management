"""Tests for ``app.services.cag_sftp`` parsing + config helpers.

The transport layer (paramiko) is exercised via integration tests on a
real SFTP host, not here. We do unit-test the host-key verification and
multi-key-type loading helpers in isolation since they are security-
sensitive and don't require a live server.
"""
from __future__ import annotations

import base64
import hashlib

import pytest

from app.config import settings
from app.services import cag_sftp


def test_parse_error_log_handles_failed_and_accepted_lines():
    payload = (
        "Failed: Line 1 - CHILD_CATG_CODE not found\n"
        "Failed: Line 3 - Mandatory fields are not filled: SKU_CODE\n"
        "Accepted: Line 10 - SKU_DESC is truncated, exceeded maximum 60 Characters\n"
    )
    entries = cag_sftp.parse_error_log(payload, source_file="SKU_10001_20240101000000.errorLog")
    assert [e.status for e in entries] == ["Failed", "Failed", "Accepted"]
    assert entries[0].line == 1
    assert entries[0].message == "CHILD_CATG_CODE not found"
    assert entries[1].message == "Mandatory fields are not filled: SKU_CODE"
    assert entries[2].source_file == "SKU_10001_20240101000000.errorLog"


def test_parse_error_log_falls_back_for_unrecognised_lines():
    entries = cag_sftp.parse_error_log("Some unknown diagnostic\n")
    assert len(entries) == 1
    assert entries[0].status == "Failed"
    assert entries[0].line == 0
    assert entries[0].message == "Some unknown diagnostic"


def test_parse_error_log_accepts_bytes():
    entries = cag_sftp.parse_error_log(
        b"Failed: Line 5 - PLU code duplicated, must be unique\n"
    )
    assert entries[0].line == 5
    assert "duplicated" in entries[0].message


def test_is_configured_false_by_default():
    cfg = cag_sftp.SFTPConfig(host="", port=22, username="")
    assert cag_sftp.is_configured(cfg) is False


def test_is_configured_true_with_password():
    cfg = cag_sftp.SFTPConfig(host="sftp.example.com", port=22, username="u", password="p")
    assert cag_sftp.is_configured(cfg) is True


def test_is_configured_true_with_key_path():
    cfg = cag_sftp.SFTPConfig(host="h", port=22, username="u", key_path="/tmp/k")
    assert cag_sftp.is_configured(cfg) is True


def test_working_dir_uses_tenant_folder():
    cfg = cag_sftp.SFTPConfig(host="h", port=22, username="u", tenant_folder="200151")
    assert cfg.working_dir == "200151/Inbound/Working"
    assert cfg.error_dir == "200151/Inbound/Error"
    assert cfg.archive_dir == "200151/Inbound/Archive"


# ---------------------------------------------------------------------------
# Host-key fingerprint verification
# ---------------------------------------------------------------------------

class _FakeServerKey:
    """Stand-in for ``paramiko.PKey`` exposing the bytes used to compute
    an OpenSSH SHA-256 fingerprint."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def asbytes(self) -> bytes:
        return self._payload


def _expected_fp(payload: bytes) -> str:
    return base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii").rstrip("=")


def test_normalize_fingerprint_strips_prefix_and_padding():
    fp = "AbCdEfG="
    # Both the SHA256:-prefixed form and the bare form normalise to the same.
    assert cag_sftp._normalize_fingerprint(f"SHA256:{fp}") == "AbCdEfG"
    assert cag_sftp._normalize_fingerprint(fp) == "AbCdEfG"
    assert cag_sftp._normalize_fingerprint("") == ""


def test_server_fingerprint_sha256_matches_openssh_format():
    payload = b"ssh-ed25519-AAAA-fake-key-bytes"
    assert cag_sftp._server_fingerprint_sha256(_FakeServerKey(payload)) == _expected_fp(payload)


def test_from_settings_picks_up_host_fingerprint(monkeypatch):
    monkeypatch.setattr(settings, "CAG_SFTP_HOST", "h")
    monkeypatch.setattr(settings, "CAG_SFTP_USER", "u")
    monkeypatch.setattr(settings, "CAG_SFTP_PASSWORD", "p")
    monkeypatch.setattr(settings, "CAG_SFTP_HOST_FINGERPRINT", "SHA256:abcd")
    cfg = cag_sftp.SFTPConfig.from_settings()
    assert cfg.host_fingerprint == "SHA256:abcd"


class _FakeTransport:
    """Minimal paramiko.Transport stand-in that records calls so we can
    assert the host-key gate runs *before* any authentication call."""

    def __init__(self, server_key_bytes: bytes) -> None:
        self._server_key = _FakeServerKey(server_key_bytes)
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def start_client(self, timeout: int = 30) -> None:
        self.calls.append(("start_client", {"timeout": timeout}))

    def get_remote_server_key(self):
        self.calls.append(("get_remote_server_key", {}))
        return self._server_key

    def auth_password(self, username: str, password: str) -> None:
        self.calls.append(("auth_password", {"username": username, "password": password}))

    def auth_publickey(self, username: str, key) -> None:
        self.calls.append(("auth_publickey", {"username": username}))

    def close(self) -> None:
        self.closed = True


def _patch_paramiko(monkeypatch, transport: _FakeTransport, sftp_client=object()):
    """Install a stub ``paramiko`` module that hands back ``transport``
    for ``Transport(...)`` and ``sftp_client`` for ``SFTPClient.from_transport``.
    """
    import sys
    import types

    fake = types.SimpleNamespace(
        Transport=lambda addr: transport,
        SFTPClient=types.SimpleNamespace(from_transport=lambda t: sftp_client),
        SSHException=Exception,
        Ed25519Key=type("Ed25519Key", (), {}),
        ECDSAKey=type("ECDSAKey", (), {}),
        RSAKey=type("RSAKey", (), {}),
        DSSKey=type("DSSKey", (), {}),
    )
    monkeypatch.setitem(sys.modules, "paramiko", fake)


def test_open_client_rejects_mismatched_host_fingerprint(monkeypatch):
    transport = _FakeTransport(b"genuine-server-key")
    _patch_paramiko(monkeypatch, transport)

    cfg = cag_sftp.SFTPConfig(
        host="h", port=22, username="u", password="p",
        host_fingerprint="SHA256:" + _expected_fp(b"DIFFERENT-key"),
    )
    with pytest.raises(cag_sftp.SFTPTransportError) as exc:
        cag_sftp._open_client(cfg)
    assert "host-key mismatch" in str(exc.value).lower()
    # The transport must be torn down and credentials must NOT have been sent.
    assert transport.closed is True
    method_names = [c[0] for c in transport.calls]
    assert "auth_password" not in method_names
    assert "auth_publickey" not in method_names


def test_open_client_accepts_matching_host_fingerprint(monkeypatch):
    payload = b"genuine-server-key"
    transport = _FakeTransport(payload)
    _patch_paramiko(monkeypatch, transport)

    cfg = cag_sftp.SFTPConfig(
        host="h", port=22, username="u", password="p",
        host_fingerprint="SHA256:" + _expected_fp(payload),
    )
    client, returned_transport = cag_sftp._open_client(cfg)
    assert returned_transport is transport
    method_names = [c[0] for c in transport.calls]
    # Host key was checked before auth.
    assert method_names.index("get_remote_server_key") < method_names.index("auth_password")


def test_open_client_warns_when_fingerprint_unpinned(monkeypatch, caplog):
    transport = _FakeTransport(b"key")
    _patch_paramiko(monkeypatch, transport)

    cfg = cag_sftp.SFTPConfig(host="h", port=22, username="u", password="p")
    with caplog.at_level("WARNING", logger="app.services.cag_sftp"):
        cag_sftp._open_client(cfg)
    assert any("not pinned" in r.message for r in caplog.records)
