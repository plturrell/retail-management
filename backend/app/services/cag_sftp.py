"""CAG / NEC Jewel POS SFTP transport.

Implements the upload + error-log polling described in
``docs/CAG - NEC Retail POS Onboarding Guides/Import and Export Sales
Interface/[Latest] CAG NEC - SFTP guide v1.1.pdf``.

Folder layout (per the onboarding guide):

- ``<Tenant>/Inbound/Working`` — tenant uploads master TXT files here
  (read+write); the import scheduler picks them up every 3 hours.
- ``<Tenant>/Inbound/Error``   — D365FO drops ``*.errorLog`` files here
  when an upload fails (read only).
- ``<Tenant>/Inbound/Archive`` — successful uploads are moved here
  (read only).

Authentication uses ``paramiko``. Either ``CAG_SFTP_KEY_PATH`` (preferred)
or ``CAG_SFTP_PASSWORD`` must be configured. The module degrades cleanly
when ``paramiko`` is not installed (e.g. in unit tests) — :func:`is_configured`
returns ``False`` and uploads raise :class:`SFTPConfigurationError`.

The pure parser :func:`parse_error_log` is exercised by the test suite
without any network or paramiko dependency.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from app.config import settings

log = logging.getLogger(__name__)


class SFTPConfigurationError(RuntimeError):
    """Raised when CAG SFTP env settings are incomplete."""


class SFTPTransportError(RuntimeError):
    """Raised when paramiko surfaces a transport-level error."""


# ---------------------------------------------------------------------------
# Error-log parsing (no network dependency)
# ---------------------------------------------------------------------------

# Spec example (SFTP guide v1.1, Inbound/Error section):
#   Failed: Line 1 - CHILD_CATG_CODE not found
#   Failed: Line 3 - Mandatory fields are not filled: SKU_CODE
#   Accepted: Line 10 - SKU_DESC is truncated, exceeded maximum 60 Characters
_LOG_LINE_RE = re.compile(r"^(?P<status>Failed|Accepted)\s*:\s*Line\s*(?P<line>\d+)\s*-\s*(?P<msg>.*)$")


@dataclass
class ErrorLogEntry:
    status: str  # "Failed" or "Accepted"
    line: int
    message: str
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "line": self.line,
            "message": self.message,
            "source_file": self.source_file,
        }


def parse_error_log(content: str | bytes, *, source_file: str | None = None) -> list[ErrorLogEntry]:
    """Parse an ``*.errorLog`` payload into structured rows."""
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = content
    entries: list[ErrorLogEntry] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LOG_LINE_RE.match(line)
        if not m:
            # Unrecognised diagnostic; preserve verbatim with line=0.
            entries.append(ErrorLogEntry("Failed", 0, line, source_file))
            continue
        entries.append(
            ErrorLogEntry(
                status=m.group("status"),
                line=int(m.group("line")),
                message=m.group("msg").strip(),
                source_file=source_file,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SFTPConfig:
    host: str
    port: int
    username: str
    password: str = ""
    key_path: str = ""
    key_passphrase: str = ""
    tenant_folder: str = ""
    inbound_working: str = "Inbound/Working"
    inbound_error: str = "Inbound/Error"
    inbound_archive: str = "Inbound/Archive"

    @classmethod
    def from_settings(cls) -> "SFTPConfig":
        return cls(
            host=settings.CAG_SFTP_HOST,
            port=int(settings.CAG_SFTP_PORT or 22),
            username=settings.CAG_SFTP_USER,
            password=settings.CAG_SFTP_PASSWORD,
            key_path=settings.CAG_SFTP_KEY_PATH,
            key_passphrase=settings.CAG_SFTP_KEY_PASSPHRASE,
            tenant_folder=settings.CAG_SFTP_TENANT_FOLDER,
            inbound_working=settings.CAG_SFTP_INBOUND_WORKING,
            inbound_error=settings.CAG_SFTP_INBOUND_ERROR,
            inbound_archive=settings.CAG_SFTP_INBOUND_ARCHIVE,
        )

    @property
    def working_dir(self) -> str:
        return _join(self.tenant_folder, self.inbound_working) if self.tenant_folder else self.inbound_working

    @property
    def error_dir(self) -> str:
        return _join(self.tenant_folder, self.inbound_error) if self.tenant_folder else self.inbound_error

    @property
    def archive_dir(self) -> str:
        return _join(self.tenant_folder, self.inbound_archive) if self.tenant_folder else self.inbound_archive


def is_configured(config: SFTPConfig | None = None) -> bool:
    cfg = config or SFTPConfig.from_settings()
    if not (cfg.host and cfg.username):
        return False
    return bool(cfg.password) or bool(cfg.key_path)


def _join(*parts: str) -> str:
    """POSIX-style path join (paramiko paths are always forward-slash)."""
    cleaned = [p.strip("/") for p in parts if p]
    return "/".join(cleaned)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

@dataclass
class UploadResult:
    files_uploaded: list[str] = field(default_factory=list)
    bytes_uploaded: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_uploaded": list(self.files_uploaded),
            "bytes_uploaded": self.bytes_uploaded,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "errors": list(self.errors),
        }


def _open_client(config: SFTPConfig):
    """Return an open paramiko ``SFTPClient`` plus its underlying transport.

    Caller is responsible for closing both. Lives behind a function so the
    rest of the module can be imported without paramiko present.
    """
    try:
        import paramiko  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise SFTPConfigurationError(
            "paramiko is not installed; run `pip install paramiko==3.5.0`"
        ) from exc

    if not is_configured(config):
        raise SFTPConfigurationError(
            "CAG SFTP credentials missing; set CAG_SFTP_HOST/USER and either "
            "CAG_SFTP_KEY_PATH or CAG_SFTP_PASSWORD in the environment."
        )

    transport = paramiko.Transport((config.host, config.port))
    try:
        if config.key_path:
            pkey = paramiko.RSAKey.from_private_key_file(
                os.path.expanduser(config.key_path),
                password=config.key_passphrase or None,
            )
            transport.connect(username=config.username, pkey=pkey)
        else:
            transport.connect(username=config.username, password=config.password)
        client = paramiko.SFTPClient.from_transport(transport)
        if client is None:
            raise SFTPTransportError("Failed to open SFTP channel")
        return client, transport
    except Exception:
        transport.close()
        raise


def _ensure_remote_dir(client, path: str) -> None:
    """``mkdir -p`` for SFTP. Silently ignores existing directories."""
    parts = path.strip("/").split("/")
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else part
        try:
            client.stat(current)
        except IOError:
            try:
                client.mkdir(current)
            except IOError as exc:
                # Race or permission issue — re-stat to confirm.
                try:
                    client.stat(current)
                except IOError:
                    raise SFTPTransportError(f"Cannot create remote dir {current!r}") from exc


def upload_files(
    files: Mapping[str, bytes],
    *,
    config: SFTPConfig | None = None,
) -> UploadResult:
    """Upload a bundle of TXT files to ``Inbound/Working/<tenant>/``.

    ``files`` maps remote filename → byte payload (already CRLF-terminated
    per :mod:`app.services.nec_jewel_txt`). Files are written to a
    ``.partial`` name first and renamed atomically so D365FO never picks
    up a half-written file mid-transfer.
    """
    cfg = config or SFTPConfig.from_settings()
    result = UploadResult()
    client, transport = _open_client(cfg)
    try:
        _ensure_remote_dir(client, cfg.working_dir)
        for fname, payload in files.items():
            remote_final = _join(cfg.working_dir, fname)
            remote_partial = remote_final + ".partial"
            try:
                with client.open(remote_partial, "wb") as fh:
                    fh.write(payload)
                # Atomic rename — paramiko maps to SFTP RENAME (POSIX semantics).
                try:
                    client.posix_rename(remote_partial, remote_final)
                except (AttributeError, IOError):
                    # Fallback to plain rename for servers without posix-rename ext.
                    try:
                        client.remove(remote_final)
                    except IOError:
                        pass
                    client.rename(remote_partial, remote_final)
                result.files_uploaded.append(fname)
                result.bytes_uploaded += len(payload)
                log.info("CAG SFTP uploaded %s (%d bytes)", fname, len(payload))
            except Exception as exc:  # noqa: BLE001 - record and continue
                msg = f"upload failed for {fname}: {exc}"
                log.exception(msg)
                result.errors.append(msg)
    finally:
        result.finished_at = datetime.utcnow()
        try:
            client.close()
        finally:
            transport.close()
    return result


def fetch_error_logs(
    *,
    config: SFTPConfig | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> list[ErrorLogEntry]:
    """List ``*.errorLog`` files in ``Inbound/Error`` and parse them."""
    cfg = config or SFTPConfig.from_settings()
    client, transport = _open_client(cfg)
    parsed: list[ErrorLogEntry] = []
    try:
        try:
            attrs = client.listdir_attr(cfg.error_dir)
        except IOError:
            return []
        # Sort newest first.
        attrs.sort(key=lambda a: getattr(a, "st_mtime", 0) or 0, reverse=True)
        for entry in attrs[:limit]:
            name = entry.filename
            if not name.lower().endswith(".errorlog"):
                continue
            mtime = getattr(entry, "st_mtime", None)
            if since and mtime and datetime.utcfromtimestamp(mtime) < since:
                continue
            remote = _join(cfg.error_dir, name)
            try:
                with client.open(remote, "rb") as fh:
                    payload = fh.read()
            except IOError as exc:
                log.warning("Could not read %s: %s", remote, exc)
                continue
            parsed.extend(parse_error_log(payload, source_file=name))
    finally:
        try:
            client.close()
        finally:
            transport.close()
    return parsed


__all__ = [
    "ErrorLogEntry",
    "SFTPConfig",
    "SFTPConfigurationError",
    "SFTPTransportError",
    "UploadResult",
    "fetch_error_logs",
    "is_configured",
    "parse_error_log",
    "upload_files",
]
