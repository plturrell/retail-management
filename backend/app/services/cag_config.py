"""Firestore-backed configuration for CAG / NEC Jewel POS integration.

The owner-facing settings UI writes to ``system_config/cag_nec``; this
module merges that doc with environment defaults from
:mod:`app.config.settings` so existing ``.env``-driven deployments keep
working unchanged. Firestore values take precedence when set.

Secrets (``password``, ``key_passphrase``) are stored alongside the
non-secret fields. The HTTP layer never echoes them back to clients —
:func:`public_view` returns ``has_password`` / ``has_key_passphrase``
booleans instead of the raw values.

Layout::

    system_config/cag_nec
      host: str
      port: int
      username: str
      password: str           # secret
      key_path: str
      key_passphrase: str     # secret
      tenant_folder: str
      inbound_working: str    # default "Inbound/Working"
      inbound_error: str
      inbound_archive: str
      default_nec_store_id: str
      default_taxable: bool
      updated_at: ISO timestamp
      updated_by: email
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.cag_sftp import SFTPConfig

log = logging.getLogger(__name__)

CONFIG_COLLECTION = "system_config"
CONFIG_DOC_ID = "cag_nec"

SECRET_FIELDS = ("password", "key_passphrase")


@dataclass
class CagConfig:
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    key_path: str = ""
    key_passphrase: str = ""
    tenant_folder: str = ""
    inbound_working: str = "Inbound/Working"
    inbound_error: str = "Inbound/Error"
    inbound_archive: str = "Inbound/Archive"
    # SHA-256 host-key fingerprint pinned for the SFTP host. See
    # ``app.services.cag_sftp._open_client`` for verification semantics.
    host_fingerprint: str = ""
    default_nec_store_id: str = ""
    default_taxable: bool = True
    # Cloud Scheduler-driven push. ``scheduler_cron`` is informational — the
    # actual job lives in Cloud Scheduler and is provisioned via
    # ``backend/scripts/setup_cag_scheduler.sh``. The defaults below are read
    # by ``POST /api/cag/export/push/scheduled`` and the on-demand test
    # endpoint, taking precedence over the env-var fallbacks.
    scheduler_enabled: bool = True
    scheduler_cron: str = "0 */3 * * *"
    scheduler_default_tenant: str = ""
    scheduler_default_store_id: str = ""
    scheduler_default_taxable: bool = False
    scheduler_last_run_at: str = ""
    scheduler_last_run_status: str = ""  # "success" | "failed" | ""
    scheduler_last_run_message: str = ""
    scheduler_last_run_files: int = 0
    scheduler_last_run_bytes: int = 0
    scheduler_last_run_trigger: str = ""  # "scheduler" | "manual"
    updated_at: str = ""
    updated_by: str = ""

    def to_sftp_config(self) -> SFTPConfig:
        return SFTPConfig(
            host=self.host,
            port=int(self.port or 22),
            username=self.username,
            password=self.password,
            key_path=self.key_path,
            key_passphrase=self.key_passphrase,
            tenant_folder=self.tenant_folder,
            inbound_working=self.inbound_working or "Inbound/Working",
            inbound_error=self.inbound_error or "Inbound/Error",
            inbound_archive=self.inbound_archive or "Inbound/Archive",
            host_fingerprint=self.host_fingerprint,
        )

    def public_view(self) -> dict[str, Any]:
        """Dict suitable for the GET endpoint — secrets masked."""
        d = asdict(self)
        d["has_password"] = bool(self.password)
        d["has_key_passphrase"] = bool(self.key_passphrase)
        for f in SECRET_FIELDS:
            d.pop(f, None)
        return d


def _env_defaults() -> dict[str, Any]:
    return {
        "host": settings.CAG_SFTP_HOST,
        "port": int(settings.CAG_SFTP_PORT or 22),
        "username": settings.CAG_SFTP_USER,
        "password": settings.CAG_SFTP_PASSWORD,
        "key_path": settings.CAG_SFTP_KEY_PATH,
        "key_passphrase": settings.CAG_SFTP_KEY_PASSPHRASE,
        "tenant_folder": settings.CAG_SFTP_TENANT_FOLDER,
        "inbound_working": settings.CAG_SFTP_INBOUND_WORKING,
        "inbound_error": settings.CAG_SFTP_INBOUND_ERROR,
        "inbound_archive": settings.CAG_SFTP_INBOUND_ARCHIVE,
        "host_fingerprint": settings.CAG_SFTP_HOST_FINGERPRINT,
    }


def _read_firestore_doc(fs_db: Any) -> dict[str, Any]:
    if fs_db is None:
        return {}
    try:
        snap = fs_db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()
    except Exception as exc:  # noqa: BLE001 - defensive against transient Firestore issues
        log.warning("Failed to read CAG config from Firestore: %s", exc)
        return {}
    if not getattr(snap, "exists", False):
        return {}
    data = snap.to_dict() or {}
    return data


def load_config(fs_db: Any | None = None) -> CagConfig:
    """Merge env defaults with Firestore overrides (Firestore wins)."""
    merged = _env_defaults()
    if fs_db is not None:
        overrides = _read_firestore_doc(fs_db)
        for key, value in overrides.items():
            # Don't let an empty Firestore value clobber a meaningful env default.
            if value in (None, ""):
                continue
            merged[key] = value
        merged.setdefault("default_nec_store_id", overrides.get("default_nec_store_id", ""))
        merged.setdefault("default_taxable", overrides.get("default_taxable", True))
        merged.setdefault("updated_at", overrides.get("updated_at", ""))
        merged.setdefault("updated_by", overrides.get("updated_by", ""))
    return CagConfig(**{k: merged.get(k, v) for k, v in CagConfig().__dict__.items() if k in merged or hasattr(CagConfig(), k)})


def save_config(
    fs_db: Any,
    patch: dict[str, Any],
    *,
    updated_by: str = "",
    keep_secrets: bool = True,
) -> CagConfig:
    """Apply ``patch`` to the persisted config and return the merged view.

    When ``keep_secrets=True`` and the patch lacks a secret field (or the
    incoming value is empty), the existing secret is preserved. The UI
    sends an empty string for ``password`` / ``key_passphrase`` when the
    operator does not want to change them.
    """
    if fs_db is None:
        raise RuntimeError("Firestore client unavailable; cannot persist CAG config")

    existing = _read_firestore_doc(fs_db)
    data = dict(existing)

    # Update non-secret fields straight through (empty string clears).
    for key in (
        "host", "port", "username", "key_path", "tenant_folder",
        "inbound_working", "inbound_error", "inbound_archive",
        "host_fingerprint",
        "default_nec_store_id", "default_taxable",
        "scheduler_enabled", "scheduler_cron",
        "scheduler_default_tenant", "scheduler_default_store_id",
        "scheduler_default_taxable",
    ):
        if key in patch:
            value = patch[key]
            if key == "port":
                try:
                    value = int(value or 22)
                except (TypeError, ValueError):
                    value = 22
            if key in ("default_taxable", "scheduler_enabled", "scheduler_default_taxable"):
                value = bool(value)
            data[key] = value

    # Secrets: only write when the patch carries a non-empty value, unless
    # caller explicitly opts out of preservation.
    for secret in SECRET_FIELDS:
        if secret in patch:
            incoming = patch[secret]
            if incoming or not keep_secrets:
                data[secret] = incoming or ""

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    if updated_by:
        data["updated_by"] = updated_by

    fs_db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).set(data, merge=False)
    return load_config(fs_db)


def clear_config(fs_db: Any) -> None:
    if fs_db is None:
        return
    fs_db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).delete()


def record_scheduler_run(
    fs_db: Any,
    *,
    status: str,
    message: str = "",
    files: int = 0,
    bytes_: int = 0,
    trigger: str = "scheduler",
) -> None:
    """Persist the most recent scheduled-push outcome on the config doc.

    Best-effort: never raises. Used by both the Cloud-Scheduler endpoint and
    the owner-driven on-demand test so the Settings UI can show last-run
    health without a separate audit collection.
    """
    if fs_db is None:
        return
    try:
        fs_db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).set(
            {
                "scheduler_last_run_at": datetime.now(timezone.utc).isoformat(),
                "scheduler_last_run_status": status,
                "scheduler_last_run_message": message[:500],
                "scheduler_last_run_files": int(files or 0),
                "scheduler_last_run_bytes": int(bytes_ or 0),
                "scheduler_last_run_trigger": trigger,
            },
            merge=True,
        )
    except Exception as exc:  # noqa: BLE001 - telemetry must not break the push
        log.warning("Failed to record scheduler run telemetry: %s", exc)


__all__ = [
    "CONFIG_COLLECTION",
    "CONFIG_DOC_ID",
    "CagConfig",
    "SECRET_FIELDS",
    "clear_config",
    "load_config",
    "record_scheduler_run",
    "save_config",
]
