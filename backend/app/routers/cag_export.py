"""HTTP surface for the CAG / NEC Jewel POS master-file export.

Three endpoints:

- ``GET  /api/cag/export/txt``    — build the 6 spec-compliant TXT files
                                    (CATG/SKU/PLU/PRICE/INVDETAILS/PROMO)
                                    and stream them back as a single ZIP.
- ``POST /api/cag/export/push``   — same as above, but pushes the bundle
                                    to ``Inbound/Working/<tenant>/`` over
                                    SFTP and returns the run summary.
- ``GET  /api/cag/export/errors`` — read the latest ``*.errorLog`` files
                                    from ``Inbound/Error`` and return
                                    parsed entries.

The Excel artefact remains available at
``GET /api/exports/nec-jewel`` (see :mod:`app.routers.data_quality`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from google.cloud.firestore_v1.client import Client as FirestoreClient
from pydantic import BaseModel

from app.auth.dependencies import RoleEnum, require_any_store_role, require_scheduler_oidc
from app.config import settings
from app.firestore import get_firestore_db
from app.services import cag_config, cag_history, cag_sftp
from app.services.nec_jewel_bundle import build_master_bundle
from app.services.nec_jewel_export import (
    BRAND_NAME,
    DEFAULT_INV_STORE_CODE,
    fetch_sellable_skus_from_firestore,
)
from app.services.nec_jewel_preview import build_preview
from app.services.store_identity import canonicalize_store_code_input

router = APIRouter(prefix="/api/cag/export", tags=["cag-export"])


class PushResponse(BaseModel):
    files_uploaded: list[str]
    bytes_uploaded: int
    counts: dict[str, int]
    started_at: str
    finished_at: str | None
    errors: list[str]


class ErrorEntryResponse(BaseModel):
    status: str
    line: int
    message: str
    source_file: str | None


def _resolve_tenant(tenant_code: str | None, fs_db: FirestoreClient | None = None) -> str:
    code = tenant_code
    if not code and fs_db is not None:
        code = cag_config.load_config(fs_db).tenant_folder
    code = code or settings.CAG_SFTP_TENANT_FOLDER
    if not code:
        raise HTTPException(
            status_code=400,
            detail=(
                "CAG tenant code missing. Pass ?tenant_code=... or configure it in "
                "Settings → CAG / NEC POS, or set CAG_SFTP_TENANT_FOLDER in the env."
            ),
        )
    return code


def _validate_nec_store_id(store_id: str, *, status_code: int) -> str:
    normalized = str(store_id or "").strip()
    if len(normalized) != 5 or not normalized.isdigit():
        raise HTTPException(
            status_code=status_code,
            detail="NEC Store ID must be the 5-digit NEC-assigned Store ID, e.g. 80001.",
        )
    return normalized


def _resolve_store_overrides(
    fs_db: FirestoreClient,
    *,
    tenant_code: str | None,
    store_code: str | None,
    nec_store_id: str | None,
    taxable: bool | None,
) -> tuple[str, str, bool]:
    """Merge query overrides → per-store fields → CAG settings → env defaults.

    Returns ``(tenant, store_id, taxable)``. Raises 400 when the store ID
    cannot be resolved from any source.
    """
    store_fields = _resolve_store_nec_fields(fs_db, canonicalize_store_code_input(store_code))
    cfg = cag_config.load_config(fs_db) if fs_db is not None else None

    # Tenant: explicit query → per-store NEC tenant → settings/env.
    tenant = tenant_code or store_fields.get("nec_tenant_code") or ""
    if not tenant:
        tenant = _resolve_tenant(None, fs_db)  # raises 400 with helpful message

    # Store ID: explicit query → per-store doc → settings default.
    store_id = nec_store_id or store_fields.get("nec_store_id") or ""
    if not store_id and cfg is not None:
        store_id = cfg.default_nec_store_id or ""
    if not store_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "NEC Store ID missing. Pass ?nec_store_id=..., set it on the store doc, "
                "or configure a default in Settings → CAG / NEC POS."
            ),
        )
    store_id = _validate_nec_store_id(store_id, status_code=400)

    # Taxable: explicit query → per-store doc → settings default → True.
    if taxable is None:
        per_store = store_fields.get("nec_taxable")
        if per_store is None and cfg is not None:
            taxable_resolved = cfg.default_taxable
        elif per_store is None:
            taxable_resolved = True
        else:
            taxable_resolved = bool(per_store)
    else:
        taxable_resolved = bool(taxable)

    return tenant, store_id, taxable_resolved


def _resolve_store_nec_fields(fs_db: FirestoreClient, store_code: str | None) -> dict[str, Any]:
    """Look up per-store NEC fields (``nec_store_id``, ``nec_taxable``,
    ``nec_tenant_code``) from the matching ``stores`` doc, if any. Returns
    the empty dict when no store matches.
    """
    if fs_db is None or not store_code:
        return {}
    try:
        for snap in fs_db.collection("stores").stream():
            data = snap.to_dict() or {}
            if data.get("store_code") == store_code:
                return {
                    "nec_store_id": data.get("nec_store_id"),
                    "nec_taxable": data.get("nec_taxable"),
                    "nec_tenant_code": data.get("nec_tenant_code"),
                }
    except Exception:  # noqa: BLE001 - per-store lookup is best-effort
        return {}
    return {}


def _build_bundle(
    fs_db: FirestoreClient,
    *,
    brand: str,
    store_code: str | None,
    inv_store_code: str,
    include_drafts: bool,
    tenant_code: str,
    nec_store_id: str,
    taxable: bool,
):
    normalized_store = canonicalize_store_code_input(store_code)
    normalized_inv = canonicalize_store_code_input(inv_store_code) or DEFAULT_INV_STORE_CODE
    products, _excluded = fetch_sellable_skus_from_firestore(
        fs_db,
        brand_name=brand,
        store_code=normalized_store,
        inv_store_code=normalized_inv,
        include_drafts=include_drafts,
    )
    if not products:
        raise HTTPException(
            status_code=404,
            detail="No sellable products are ready for CAG NEC POS export.",
        )
    return build_master_bundle(
        products,
        tenant_code=tenant_code,
        store_id=nec_store_id,
        taxable=taxable,
    )


@router.get("/txt")
async def export_txt_bundle(
    tenant_code: str | None = Query(None, description="6/7-digit CAG Customer No."),
    nec_store_id: str | None = Query(None, description="5-digit NEC-assigned Store ID (overrides per-store doc)"),
    brand: str = Query(BRAND_NAME),
    store_code: str | None = Query(None, alias="store"),
    inv_store_code: str = Query(DEFAULT_INV_STORE_CODE, alias="inv_store"),
    include_drafts: bool = Query(False),
    taxable: bool | None = Query(None, description="Override per-store taxable flag (True = landside / G)"),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    fs_db: FirestoreClient = Depends(get_firestore_db),
) -> StreamingResponse:
    tenant, store_id, store_taxable = _resolve_store_overrides(
        fs_db,
        tenant_code=tenant_code,
        store_code=store_code,
        nec_store_id=nec_store_id,
        taxable=taxable,
    )
    bundle = _build_bundle(
        fs_db,
        brand=brand,
        store_code=store_code,
        inv_store_code=inv_store_code,
        include_drafts=include_drafts,
        tenant_code=tenant,
        nec_store_id=store_id,
        taxable=store_taxable,
    )
    payload = bundle.as_zip()
    fname = f"cag_nec_master_{tenant}_{bundle.generated_at.strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        BytesIO(payload),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Cag-File-Counts": ",".join(f"{k}={v}" for k, v in bundle.counts.items()),
        },
    )


def _do_push(
    fs_db: FirestoreClient,
    *,
    tenant_code: str,
    nec_store_id: str,
    taxable: bool,
    brand: str = BRAND_NAME,
    store_code: str | None = None,
    inv_store_code: str = DEFAULT_INV_STORE_CODE,
    include_drafts: bool = False,
    triggered_by: str = "",
    trigger_kind: str = "manual",
) -> PushResponse:
    """Build the master bundle and push it to the configured SFTP target.

    Shared body for the operator-triggered ``POST /push`` and the
    Cloud-Scheduler-triggered ``POST /push/scheduled`` endpoints. Each
    attempt is recorded in ``cag_sftp_runs`` so the owner UI can show a
    push history independent of the single-row scheduler last-run doc.
    """
    cfg = cag_config.load_config(fs_db).to_sftp_config()
    if not cag_sftp.is_configured(cfg):
        raise HTTPException(
            status_code=503,
            detail=(
                "CAG SFTP is not configured. Open Settings → CAG / NEC POS to enter "
                "host/user and either a key path or password."
            ),
        )
    bundle = _build_bundle(
        fs_db,
        brand=brand,
        store_code=store_code,
        inv_store_code=inv_store_code,
        include_drafts=include_drafts,
        tenant_code=tenant_code,
        nec_store_id=nec_store_id,
        taxable=taxable,
    )
    try:
        upload = cag_sftp.upload_files(bundle.files, config=cfg)
    except cag_sftp.SFTPConfigurationError as exc:
        cag_history.record_run(
            fs_db,
            tenant_code=tenant_code,
            nec_store_id=nec_store_id,
            taxable=taxable,
            counts=bundle.counts,
            files_uploaded=[],
            bytes_uploaded=0,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            errors=[f"SFTPConfigurationError: {exc}"],
            triggered_by=triggered_by,
            trigger_kind=trigger_kind,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except cag_sftp.SFTPTransportError as exc:
        cag_history.record_run(
            fs_db,
            tenant_code=tenant_code,
            nec_store_id=nec_store_id,
            taxable=taxable,
            counts=bundle.counts,
            files_uploaded=[],
            bytes_uploaded=0,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            errors=[f"SFTPTransportError: {exc}"],
            triggered_by=triggered_by,
            trigger_kind=trigger_kind,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cag_history.record_run(
        fs_db,
        tenant_code=tenant_code,
        nec_store_id=nec_store_id,
        taxable=taxable,
        counts=bundle.counts,
        files_uploaded=upload.files_uploaded,
        bytes_uploaded=upload.bytes_uploaded,
        started_at=upload.started_at,
        finished_at=upload.finished_at,
        errors=upload.errors,
        triggered_by=triggered_by,
        trigger_kind=trigger_kind,
    )
    return PushResponse(
        files_uploaded=upload.files_uploaded,
        bytes_uploaded=upload.bytes_uploaded,
        counts=bundle.counts,
        started_at=upload.started_at.isoformat(),
        finished_at=upload.finished_at.isoformat() if upload.finished_at else None,
        errors=upload.errors,
    )


class ScheduledPushRequest(BaseModel):
    tenant_code: str | None = None
    nec_store_id: str | None = None
    taxable: bool | None = None


@router.post("/push", response_model=PushResponse)
async def push_to_sftp(
    tenant_code: str | None = Query(None),
    nec_store_id: str | None = Query(None),
    brand: str = Query(BRAND_NAME),
    store_code: str | None = Query(None, alias="store"),
    inv_store_code: str = Query(DEFAULT_INV_STORE_CODE, alias="inv_store"),
    include_drafts: bool = Query(False),
    taxable: bool | None = Query(None),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    fs_db: FirestoreClient = Depends(get_firestore_db),
) -> PushResponse:
    tenant, store_id, store_taxable = _resolve_store_overrides(
        fs_db,
        tenant_code=tenant_code,
        store_code=store_code,
        nec_store_id=nec_store_id,
        taxable=taxable,
    )
    return _do_push(
        fs_db,
        tenant_code=tenant,
        nec_store_id=store_id,
        taxable=store_taxable,
        brand=brand,
        store_code=store_code,
        inv_store_code=inv_store_code,
        include_drafts=include_drafts,
    )


def _resolve_scheduled_defaults(
    fs_db: FirestoreClient,
    body: "ScheduledPushRequest",
) -> tuple[str, str, bool]:
    """Pick the tenant/store/taxable the scheduler (or test endpoint) will use.

    Resolution order: explicit body value → scheduler-specific config →
    shared CAG config → env-var fallback. Raises 500 when nothing resolves so
    the caller surfaces a clear configuration error instead of a silent empty
    push.
    """
    cfg = cag_config.load_config(fs_db) if fs_db is not None else None
    tenant = (
        body.tenant_code
        or (cfg.scheduler_default_tenant if cfg else "")
        or (cfg.tenant_folder if cfg else "")
        or settings.CAG_SCHEDULED_PUSH_DEFAULT_TENANT
        or settings.CAG_SFTP_TENANT_FOLDER
    )
    store_id = (
        body.nec_store_id
        or (cfg.scheduler_default_store_id if cfg else "")
        or (cfg.default_nec_store_id if cfg else "")
        or settings.CAG_SCHEDULED_PUSH_DEFAULT_STORE_ID
    )
    if not tenant:
        raise HTTPException(
            status_code=500,
            detail=(
                "Scheduled push misconfigured: set scheduler_default_tenant in "
                "Settings → CAG / NEC POS, or pass tenant_code in the body."
            ),
        )
    if not store_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "Scheduled push misconfigured: set scheduler_default_store_id in "
                "Settings → CAG / NEC POS, or pass nec_store_id in the body."
            ),
        )
    store_id = _validate_nec_store_id(
        store_id,
        status_code=400 if body.nec_store_id else 500,
    )
    if body.taxable is not None:
        taxable = bool(body.taxable)
    elif cfg is not None:
        taxable = bool(cfg.scheduler_default_taxable)
    else:
        taxable = False
    return tenant, store_id, taxable


def _push_with_telemetry(
    fs_db: FirestoreClient,
    *,
    tenant: str,
    store_id: str,
    taxable: bool,
    trigger: str,
) -> PushResponse:
    """Run ``_do_push`` and persist last-run telemetry on success or failure."""
    history_kind = "scheduled" if trigger == "scheduler" else trigger
    try:
        result = _do_push(
            fs_db,
            tenant_code=tenant,
            nec_store_id=store_id,
            taxable=taxable,
            triggered_by=trigger,
            trigger_kind=history_kind,
        )
    except HTTPException as exc:
        cag_config.record_scheduler_run(
            fs_db,
            status="failed",
            message=f"HTTP {exc.status_code}: {exc.detail}",
            trigger=trigger,
        )
        raise
    cag_config.record_scheduler_run(
        fs_db,
        status="success" if not result.errors else "failed",
        message="; ".join(result.errors) if result.errors else "OK",
        files=len(result.files_uploaded),
        bytes_=result.bytes_uploaded,
        trigger=trigger,
    )
    return result


@router.post("/push/scheduled", response_model=PushResponse)
def push_scheduled(
    body: ScheduledPushRequest | None = None,
    _claims: dict = Depends(require_scheduler_oidc),
    fs_db: FirestoreClient = Depends(get_firestore_db),
) -> PushResponse:
    """Cloud-Scheduler-triggered NEC CAG bundle push.

    Authenticated via Google OIDC (see ``require_scheduler_oidc``). Defaults
    to the tenant/store configured in Firestore (Settings → CAG / NEC POS),
    falling back to ``settings.CAG_SCHEDULED_PUSH_*`` env vars; pass overrides
    in the body for ad-hoc scheduler runs.
    """
    body = body or ScheduledPushRequest()
    tenant, store_id, taxable = _resolve_scheduled_defaults(fs_db, body)
    return _push_with_telemetry(
        fs_db,
        tenant=tenant,
        store_id=store_id,
        taxable=taxable,
        trigger="scheduler",
    )


@router.post("/push/test", response_model=PushResponse)
def push_scheduled_test(
    body: ScheduledPushRequest | None = None,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    fs_db: FirestoreClient = Depends(get_firestore_db),
) -> PushResponse:
    """Owner-driven mirror of the scheduled push for ad-hoc verification.

    Uses the same default-resolution path and telemetry recording as
    ``/push/scheduled`` so a manual click in the Settings page exercises the
    exact code path Cloud Scheduler will hit. ``trigger`` is recorded as
    ``manual`` so the UI can label the most recent run.
    """
    body = body or ScheduledPushRequest()
    tenant, store_id, taxable = _resolve_scheduled_defaults(fs_db, body)
    return _push_with_telemetry(
        fs_db,
        tenant=tenant,
        store_id=store_id,
        taxable=taxable,
        trigger="manual",
    )


@router.get("/errors", response_model=list[ErrorEntryResponse])
async def list_sftp_errors(
    limit: int = Query(50, ge=1, le=500),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    fs_db: FirestoreClient = Depends(get_firestore_db),
) -> list[ErrorEntryResponse]:
    cfg = cag_config.load_config(fs_db).to_sftp_config()
    if not cag_sftp.is_configured(cfg):
        raise HTTPException(
            status_code=503,
            detail="CAG SFTP is not configured.",
        )
    try:
        entries = cag_sftp.fetch_error_logs(config=cfg, limit=limit)
    except cag_sftp.SFTPConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except cag_sftp.SFTPTransportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [ErrorEntryResponse(**e.to_dict()) for e in entries]


class PreviewIssueResponse(BaseModel):
    sku_code: str
    field: str
    severity: str
    message: str


class PreviewResponse(BaseModel):
    sellable_count: int
    excluded_count: int
    counts: dict[str, int]
    tenant_code: str
    nec_store_id: str
    taxable: bool
    is_ready: bool
    errors: list[PreviewIssueResponse]
    warnings: list[PreviewIssueResponse]
    excluded_summary: dict[str, int]


@router.get("/preview", response_model=PreviewResponse)
async def preview_export(
    tenant_code: str | None = Query(None),
    nec_store_id: str | None = Query(None),
    brand: str = Query(BRAND_NAME),
    store_code: str | None = Query(None, alias="store"),
    inv_store_code: str = Query(DEFAULT_INV_STORE_CODE, alias="inv_store"),
    include_drafts: bool = Query(False),
    taxable: bool | None = Query(None),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    fs_db: FirestoreClient = Depends(get_firestore_db),
) -> PreviewResponse:
    """Dry-run the master export and report counts + spec violations.

    Mirrors the gate used by ``/txt`` and ``/push`` but never writes any
    files, so operators can fix data quality before consuming an SFTP
    upload window.
    """
    tenant, store_id, store_taxable = _resolve_store_overrides(
        fs_db,
        tenant_code=tenant_code,
        store_code=store_code,
        nec_store_id=nec_store_id,
        taxable=taxable,
    )
    normalized_store = canonicalize_store_code_input(store_code)
    normalized_inv = canonicalize_store_code_input(inv_store_code) or DEFAULT_INV_STORE_CODE
    products, excluded = fetch_sellable_skus_from_firestore(
        fs_db,
        brand_name=brand,
        store_code=normalized_store,
        inv_store_code=normalized_inv,
        include_drafts=include_drafts,
    )
    result = build_preview(
        products,
        excluded,
        tenant_code=tenant,
        nec_store_id=store_id,
        taxable=store_taxable,
    )
    return PreviewResponse(**result.to_dict())
