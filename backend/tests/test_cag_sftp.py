"""Tests for ``app.services.cag_sftp`` parsing + config helpers.

The transport layer (paramiko) is exercised via integration tests on a
real SFTP host, not here.
"""
from __future__ import annotations

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
