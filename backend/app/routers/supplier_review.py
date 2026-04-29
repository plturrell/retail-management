"""Supplier invoice / OCR review endpoints.

Serves the curated supplier-order JSON documents under
``docs/suppliers/<supplier_dir>/orders/<order_number>.json`` so the iOS
and Android Vendor Review screens can fetch real reconciliation data
instead of bundling hard-coded mocks. Documents are looked up by
``supplier_id`` (the value stored inside each JSON, e.g. ``CN-001``)
rather than by directory name, so suppliers can be re-organised on disk
without breaking client integrations.

This is a read-only, file-backed surface. Mutating workspace state is
held client-side (see ``SupplierReviewWorkspaceState`` on iOS / Android).
"""
from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import RoleEnum, require_any_store_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/supplier-review", tags=["supplier-review"])

# backend/app/routers/supplier_review.py → repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SUPPLIERS_ROOT = _REPO_ROOT / "docs" / "suppliers"


def _scan_orders() -> dict[str, dict[str, Path]]:
    """Build an index: {supplier_id: {order_number: file_path}}.

    Scans every ``*/orders/*.json`` under ``docs/suppliers/`` and groups
    by the ``supplier_id`` field inside each file. Skips files that do
    not parse or do not declare a supplier_id.
    """
    index: dict[str, dict[str, Path]] = {}
    if not _SUPPLIERS_ROOT.exists():
        return index
    for orders_dir in _SUPPLIERS_ROOT.glob("*/orders"):
        if not orders_dir.is_dir():
            continue
        for path in orders_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("supplier_review: skipping %s (%s)", path, exc)
                continue
            supplier_id = str(payload.get("supplier_id") or "").strip()
            order_number = str(payload.get("order_number") or path.stem).strip()
            if not supplier_id or not order_number:
                continue
            index.setdefault(supplier_id, {})[order_number] = path
    return index


@router.get("/{supplier_id}/orders")
async def list_supplier_orders(
    supplier_id: str,
    _: dict = Depends(require_any_store_role(RoleEnum.manager)),
) -> dict[str, Any]:
    """List every order document on file for the given supplier."""
    index = _scan_orders()
    bucket = index.get(supplier_id, {})
    orders: list[dict[str, Any]] = []
    for order_number, path in sorted(bucket.items()):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        orders.append({
            "order_number": order_number,
            "order_date": payload.get("order_date"),
            "currency": payload.get("currency"),
            "supplier_name": payload.get("supplier_name"),
            "source_document_total_amount": payload.get("source_document_total_amount"),
            "document_payment_status": payload.get("document_payment_status"),
            "item_reconciliation_status": payload.get("item_reconciliation_status"),
            "line_count": len(payload.get("line_items", []) or []),
        })
    return {
        "supplier_id": supplier_id,
        "count": len(orders),
        "orders": orders,
    }


@router.get("/{supplier_id}/orders/{order_number}")
async def get_supplier_order(
    supplier_id: str,
    order_number: str,
    _: dict = Depends(require_any_store_role(RoleEnum.manager)),
) -> dict[str, Any]:
    """Return the full reviewed order document."""
    index = _scan_orders()
    path = index.get(supplier_id, {}).get(order_number)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=f"No order {order_number!r} on file for supplier {supplier_id!r}.",
        )
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("supplier_review: failed to read %s", path)
        raise HTTPException(status_code=500, detail=f"Could not read order document: {exc}")


@router.get("/{supplier_id}/artifacts/{file_path:path}")
async def get_supplier_artifact(
    supplier_id: str,
    file_path: str,
    _: dict = Depends(require_any_store_role(RoleEnum.manager)),
) -> FileResponse:
    """Stream a source artifact (e.g. invoice scan PNG) for a supplier.

    ``file_path`` is the relative path recorded in the order document's
    ``source_artifacts[].file`` field, e.g.
    ``orders/order-364-365-2026-03-26-source.PNG``. Resolution is
    constrained to the supplier's directory under ``docs/suppliers/`` to
    prevent traversal outside that root.
    """
    index = _scan_orders()
    bucket = index.get(supplier_id)
    if not bucket:
        raise HTTPException(status_code=404, detail=f"Unknown supplier {supplier_id!r}.")

    # Any order file under this supplier shares the same supplier directory.
    supplier_dir = next(iter(bucket.values())).parent.parent
    target = (supplier_dir / file_path).resolve()
    try:
        target.relative_to(supplier_dir.resolve())
    except ValueError:
        logger.warning(
            "supplier_review: rejected path traversal supplier=%s file=%r resolved=%s",
            supplier_id, file_path, target,
        )
        raise HTTPException(status_code=400, detail="Artifact path escapes supplier directory.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact {file_path!r} not found.")

    media_type, _enc = mimetypes.guess_type(target.name)
    return FileResponse(
        path=target,
        media_type=media_type or "application/octet-stream",
        filename=target.name,
    )
