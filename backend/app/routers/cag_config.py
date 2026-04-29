"""Owner-facing settings API for the CAG / NEC POS integration.

Endpoints (all owner-only):

- ``GET    /api/cag/config``        — current merged config (secrets masked).
- ``PUT    /api/cag/config``        — patch + persist to Firestore.
- ``DELETE /api/cag/config``        — wipe Firestore overrides (env defaults
                                       remain in effect).
- ``POST   /api/cag/config/test``   — open an SFTP session against the saved
                                       (or provided) config and report status.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from google.cloud.firestore_v1.client import Client as FirestoreClient
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import RoleEnum, require_any_store_role
from app.config import settings
from app.firestore import get_firestore_db
from app.services import cag_config, cag_sftp

router = APIRouter(prefix="/api/cag/config", tags=["cag-config"])
log = logging.getLogger(__name__)


class CagConfigPatch(BaseModel):
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    # Password / key_passphrase: empty string keeps the existing secret;
    # send a non-empty value to overwrite. Use DELETE to wipe entirely.
    password: str | None = None
    key_path: str | None = None
    key_passphrase: str | None = None
    tenant_folder: str | None = None
    inbound_working: str | None = None
    inbound_error: str | None = None
    inbound_archive: str | None = None
    default_nec_store_id: str | None = None
    default_taxable: bool | None = None
    # Scheduler control surface. ``scheduler_cron`` is informational (the
    # actual cron is provisioned in Cloud Scheduler) but lets owners see and
    # document the cadence alongside the rest of the integration settings.
    scheduler_enabled: bool | None = None
    scheduler_cron: str | None = None
    scheduler_default_tenant: str | None = None
    scheduler_default_store_id: str | None = None
    scheduler_default_taxable: bool | None = None


class CagConfigPublic(BaseModel):
    host: str
    port: int
    username: str
    key_path: str
    key_passphrase: str = ""  # never returned, kept for shape parity
    tenant_folder: str
    inbound_working: str
    inbound_error: str
    inbound_archive: str
    default_nec_store_id: str
    default_taxable: bool
    scheduler_enabled: bool = True
    scheduler_cron: str = ""
    scheduler_default_tenant: str = ""
    scheduler_default_store_id: str = ""
    scheduler_default_taxable: bool = False
    scheduler_last_run_at: str = ""
    scheduler_last_run_status: str = ""
    scheduler_last_run_message: str = ""
    scheduler_last_run_files: int = 0
    scheduler_last_run_bytes: int = 0
    scheduler_last_run_trigger: str = ""
    scheduler_sa_email: str = ""
    scheduler_audience: str = ""
    has_password: bool
    has_key_passphrase: bool
    is_configured: bool
    updated_at: str
    updated_by: str

    model_config = ConfigDict(extra="ignore")


def _to_public(cfg: cag_config.CagConfig) -> CagConfigPublic:
    payload = cfg.public_view()
    payload["is_configured"] = cag_sftp.is_configured(cfg.to_sftp_config())
    payload.setdefault("key_passphrase", "")
    # Surface the env-pinned OIDC identity so the UI can show what the Cloud
    # Scheduler job authenticates as (read-only — these come from cloudbuild).
    payload["scheduler_sa_email"] = settings.CAG_SCHEDULER_SA_EMAIL or ""
    payload["scheduler_audience"] = settings.CAG_SCHEDULER_AUDIENCE or ""
    return CagConfigPublic(**payload)


@router.get("", response_model=CagConfigPublic)
async def get_config(
    fs_db: FirestoreClient = Depends(get_firestore_db),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> CagConfigPublic:
    return _to_public(cag_config.load_config(fs_db))


@router.put("", response_model=CagConfigPublic)
async def update_config(
    patch: CagConfigPatch = Body(...),
    fs_db: FirestoreClient = Depends(get_firestore_db),
    user: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> CagConfigPublic:
    if fs_db is None:
        raise HTTPException(status_code=503, detail="Firestore unavailable")
    body = patch.model_dump(exclude_unset=True)
    if not body:
        raise HTTPException(status_code=400, detail="Empty patch")
    updated_by = (user or {}).get("email", "") if isinstance(user, dict) else ""
    try:
        merged = cag_config.save_config(fs_db, body, updated_by=updated_by)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    log.info("CAG config updated by %s (%d fields)", updated_by or "?", len(body))
    return _to_public(merged)


@router.delete("", response_model=CagConfigPublic)
async def clear_overrides(
    fs_db: FirestoreClient = Depends(get_firestore_db),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> CagConfigPublic:
    cag_config.clear_config(fs_db)
    return _to_public(cag_config.load_config(fs_db))


class TestResponse(BaseModel):
    ok: bool
    message: str
    working_dir: str = ""
    error_dir: str = ""
    archive_dir: str = ""


@router.post("/test", response_model=TestResponse)
async def test_connection(
    fs_db: FirestoreClient = Depends(get_firestore_db),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> TestResponse:
    cfg = cag_config.load_config(fs_db).to_sftp_config()
    if not cag_sftp.is_configured(cfg):
        return TestResponse(
            ok=False,
            message="Missing host/username and key_path or password.",
        )
    try:
        client, transport = cag_sftp._open_client(cfg)
    except cag_sftp.SFTPConfigurationError as exc:
        return TestResponse(ok=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - network surface
        return TestResponse(ok=False, message=f"Connect failed: {exc}")

    msgs: list[str] = []
    try:
        for label, path in (
            ("working", cfg.working_dir),
            ("error", cfg.error_dir),
            ("archive", cfg.archive_dir),
        ):
            try:
                client.stat(path)
                msgs.append(f"{label} OK")
            except IOError:
                msgs.append(f"{label} missing ({path})")
    finally:
        try:
            client.close()
        finally:
            transport.close()

    ok = all("OK" in m for m in msgs)
    return TestResponse(
        ok=ok,
        message="; ".join(msgs) if msgs else "connected",
        working_dir=cfg.working_dir,
        error_dir=cfg.error_dir,
        archive_dir=cfg.archive_dir,
    )
