"""Data quality review endpoints — load, validate, and correct product data."""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from google.cloud.firestore import Client as FirestoreClient
from pydantic import BaseModel, Field

from app.auth.dependencies import RoleEnum, require_any_store_role
from app.firestore import get_firestore_db
from app.services.nec_jewel_export import (
    BRAND_NAME,
    DEFAULT_INV_STORE_CODE,
    build_workbook_bytes,
    default_export_filename,
    fetch_sellable_skus_from_firestore,
)
from app.services.store_identity import canonicalize_store_code_input

router = APIRouter(
    prefix="/api/data-quality",
    tags=["data-quality"],
)

# GST rate for computing price_excl_tax from price_incl_tax (Singapore 9%)
_GST_RATE = Decimal("0.09")
_FAR_FUTURE = date(2099, 12, 31)

# Resolve repo root relative to this file (backend/app/routers -> repo root)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MASTER_LIST_PATH = _REPO_ROOT / "data" / "master_product_list.json"

# ── Validation rules ─────────────────────────────────────────────────────────

ALL_PRODUCT_TYPES = [
    "Bracelet", "Necklace", "Ring", "Pendant", "Earring",
    "Figurine", "Sculpture", "Bookend", "Bowl", "Wall Art",
    "Vase", "Tray", "Box", "Candle Holder", "Lamp", "Clock",
    "Mirror", "Coaster",
    "Loose Gemstone", "Tumbled Stone", "Raw Specimen", "Crystal Cluster",
    "Gemstone Bead", "Cabochon",
    "Bead Strand", "Charm", "Jewellery Component",
    "Decorative Object", "Healing Crystal", "Crystal Point",
    "Gift Set", "Repair Service", "Accessory",
]

ALL_INVENTORY_CATEGORIES = [
    "finished_for_sale", "catalog_to_stock", "material", "store_operations",
]

ALL_STOCKING_STATUSES = ["in_stock", "to_order", "to_manufacture", "not_stocked"]

ALL_STOCKING_LOCATIONS = [
    "takashimaya_counter", "warehouse",
]

ALL_INVENTORY_TYPES = ["finished", "material", "purchased"]
ALL_SOURCING_STRATEGIES = ["supplier_premade", "manufactured_standard", "manufactured_custom"]


def _validate_product(p: dict) -> list[dict]:
    """Return a list of quality issues for a single product."""
    issues: list[dict] = []
    pid = p.get("id", "?")

    if not p.get("description") or len(p["description"].strip()) < 3:
        issues.append({"field": "description", "severity": "error", "message": "Description missing or too short"})

    if not p.get("material") or p["material"] in ("Unknown", "N/A", ""):
        issues.append({"field": "material", "severity": "warning", "message": "Material unknown"})

    pt = p.get("product_type", "")
    if pt not in ALL_PRODUCT_TYPES:
        issues.append({"field": "product_type", "severity": "error", "message": f"Invalid product_type: {pt}"})

    ic = p.get("inventory_category", "")
    if ic not in ALL_INVENTORY_CATEGORIES:
        issues.append({"field": "inventory_category", "severity": "error", "message": f"Invalid inventory_category: {ic}"})

    if p.get("cost_price") is None:
        issues.append({"field": "cost_price", "severity": "warning", "message": "No cost price"})

    if not p.get("sku_code"):
        issues.append({"field": "sku_code", "severity": "error", "message": "Missing SKU code"})

    if p.get("sale_ready") and not p.get("nec_plu"):
        issues.append({"field": "nec_plu", "severity": "warning", "message": "Sale-ready but no NEC PLU"})

    if not p.get("stocking_location") and p.get("stocking_status") != "not_stocked":
        issues.append({"field": "stocking_location", "severity": "warning", "message": "No stocking location assigned"})

    # Duplicate-like description
    desc = (p.get("description") or "").strip().lower()
    if desc in ("unknown", "unknown item", "unknown decorative object", "resting"):
        issues.append({"field": "description", "severity": "error", "message": "Likely OCR garbage or placeholder name"})

    return issues


# ── Request/Response models ──────────────────────────────────────────────────

class ProductCorrection(BaseModel):
    id: str
    description: str | None = None
    material: str | None = None
    product_type: str | None = None
    inventory_category: str | None = None
    inventory_type: str | None = None
    sourcing_strategy: str | None = None
    sale_ready: bool | None = None
    block_sales: bool | None = None
    stocking_status: str | None = None
    stocking_location: str | None = None
    cost_price: float | None = Field(None, ge=0)
    retail_price: float | None = Field(None, ge=0)


class BulkCorrectionRequest(BaseModel):
    corrections: list[ProductCorrection]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/products")
async def get_products(
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict[str, Any]:
    """Load the master product list with validation issues."""
    if not _MASTER_LIST_PATH.exists():
        raise HTTPException(status_code=404, detail="Master product list not found. Run the build pipeline first.")

    data = json.loads(_MASTER_LIST_PATH.read_text())
    products = data.get("products", [])

    # Validate each product
    issue_counts: Counter[str] = Counter()
    for p in products:
        issues = _validate_product(p)
        p["_quality_issues"] = issues
        p["_issue_count"] = len(issues)
        for iss in issues:
            issue_counts[iss["severity"]] += 1

    return {
        "generated_at": data.get("generated_at"),
        "total_products": len(products),
        "quality_summary": {
            "total_errors": issue_counts.get("error", 0),
            "total_warnings": issue_counts.get("warning", 0),
            "products_with_issues": sum(1 for p in products if p["_issue_count"] > 0),
            "products_clean": sum(1 for p in products if p["_issue_count"] == 0),
        },
        "reference": {
            "product_types": ALL_PRODUCT_TYPES,
            "inventory_categories": ALL_INVENTORY_CATEGORIES,
            "stocking_statuses": ALL_STOCKING_STATUSES,
            "stocking_locations": ALL_STOCKING_LOCATIONS,
            "inventory_types": ALL_INVENTORY_TYPES,
            "sourcing_strategies": ALL_SOURCING_STRATEGIES,
        },
        "products": products,
    }


@router.get("/summary")
async def get_quality_summary(
    _: dict = Depends(require_any_store_role(RoleEnum.manager)),
) -> dict[str, Any]:
    """Lightweight summary without full product list."""
    if not _MASTER_LIST_PATH.exists():
        raise HTTPException(status_code=404, detail="Master product list not found.")

    data = json.loads(_MASTER_LIST_PATH.read_text())
    products = data.get("products", [])

    errors = 0
    warnings = 0
    products_with_issues = 0
    for p in products:
        issues = _validate_product(p)
        e = sum(1 for i in issues if i["severity"] == "error")
        w = sum(1 for i in issues if i["severity"] == "warning")
        errors += e
        warnings += w
        if issues:
            products_with_issues += 1

    return {
        "generated_at": data.get("generated_at"),
        "total_products": len(products),
        "quality": {
            "errors": errors,
            "warnings": warnings,
            "products_with_issues": products_with_issues,
            "products_clean": len(products) - products_with_issues,
            "quality_score": round((len(products) - products_with_issues) / max(len(products), 1) * 100, 1),
        },
        "by_inventory_category": dict(Counter(p.get("inventory_category", "") for p in products).most_common()),
        "by_stocking_status": dict(Counter(p.get("stocking_status", "") for p in products).most_common()),
        "by_product_type": dict(Counter(p.get("product_type", "") for p in products).most_common()),
        "sale_ready_count": sum(1 for p in products if p.get("sale_ready")),
    }


@router.post("/corrections")
async def apply_corrections(
    body: BulkCorrectionRequest,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict[str, Any]:
    """Apply manual corrections to the master product list."""
    if not _MASTER_LIST_PATH.exists():
        raise HTTPException(status_code=404, detail="Master product list not found.")

    data = json.loads(_MASTER_LIST_PATH.read_text())
    products = data.get("products", [])

    # Build lookup
    product_map = {p["id"]: p for p in products}

    applied = 0
    not_found = []
    for correction in body.corrections:
        p = product_map.get(correction.id)
        if not p:
            not_found.append(correction.id)
            continue

        updates = correction.model_dump(exclude_unset=True, exclude={"id"})
        for field, value in updates.items():
            if value is not None:
                p[field] = value
        applied += 1

    # Re-validate and update summary
    data["products"] = products
    data["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["total_products"] = len(products)

    # Clean up any temp quality fields before saving
    for p in products:
        p.pop("_quality_issues", None)
        p.pop("_issue_count", None)

    # Recalculate summary
    data["summary"] = {
        "with_internal_code": sum(1 for p in products if p.get("internal_code")),
        "with_quantity": sum(1 for p in products if p.get("qty_on_hand") is not None),
        "with_price": sum(1 for p in products if p.get("cost_price") is not None),
        "sale_ready": sum(1 for p in products if p.get("sale_ready")),
        "blocked": sum(1 for p in products if p.get("block_sales")),
        "by_type": dict(Counter(p.get("product_type", "") for p in products).most_common()),
        "by_inventory_category": dict(Counter(p.get("inventory_category", "") for p in products).most_common()),
        "by_stocking_status": dict(Counter(p.get("stocking_status", "") for p in products).most_common()),
        "by_stocking_location": dict(Counter(p.get("stocking_location") or "unassigned" for p in products).most_common()),
    }

    _MASTER_LIST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))

    return {
        "applied": applied,
        "not_found": not_found,
        "total_products": len(products),
        "message": f"Applied {applied} corrections. {len(not_found)} IDs not found.",
    }


# ── Bulk Price Entry (writes to Firestore) ───────────────────────────────────

class BulkPriceEntry(BaseModel):
    """One row in a bulk price update. Match by sku_code (preferred) or legacy_code."""
    sku_code: str | None = None
    legacy_code: str | None = None
    retail_price: Decimal = Field(..., ge=0, description="GST-inclusive retail price (SGD)")


class BulkPricesRequest(BaseModel):
    prices: list[BulkPriceEntry]


def _find_sku_in_firestore(
    fs_db: FirestoreClient,
    *,
    sku_code: str | None,
    legacy_code: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (store_id, sku_doc) for a SKU matched by sku_code, then legacy_code."""
    for s in fs_db.collection("stores").stream():
        inv_ref = s.reference.collection("inventory")
        if sku_code:
            for hit in inv_ref.where("sku_code", "==", sku_code).limit(1).stream():
                return s.id, hit.to_dict() or {}
        if legacy_code:
            for hit in inv_ref.where("legacy_code", "==", legacy_code).limit(1).stream():
                return s.id, hit.to_dict() or {}
    return None, None


def _find_active_price(
    fs_db: FirestoreClient,
    *,
    store_id: str,
    sku_id: str,
    today_iso: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (price_doc_id, price_doc) for the most recent active price in this store."""
    candidates: list[tuple[str, dict[str, Any]]] = []
    for pr in fs_db.collection(f"stores/{store_id}/prices").where("sku_id", "==", sku_id).stream():
        pd = pr.to_dict() or {}
        vf = pd.get("valid_from") or ""
        vt = pd.get("valid_to") or ""
        if vf <= today_iso <= vt:
            candidates.append((pr.id, pd))
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: c[1].get("created_at") or "", reverse=True)
    return candidates[0]


@router.post("/prices/bulk")
async def bulk_update_prices(
    body: BulkPricesRequest,
    fs_db: FirestoreClient = Depends(get_firestore_db),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict[str, Any]:
    """Upsert retail prices in Firestore for many SKUs.

    For each entry:
      * Look up the SKU across all stores by sku_code, falling back to legacy_code.
      * If an active Price doc exists under that store, update price_incl/excl_tax.
      * Otherwise insert a new Price doc valid from today under that store's
        ``prices`` subcollection.
    """
    if not body.prices:
        return {"updated": 0, "created": 0, "not_found": [], "message": "No price entries provided."}

    today = date.today()
    today_iso = today.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    results: dict[str, Any] = {"updated": 0, "created": 0, "not_found": [], "errors": []}

    for entry in body.prices:
        lookup_key = entry.sku_code or entry.legacy_code
        if not lookup_key:
            results["errors"].append({"entry": entry.model_dump(), "error": "no sku_code or legacy_code"})
            continue

        store_id, sku_doc = _find_sku_in_firestore(
            fs_db, sku_code=entry.sku_code, legacy_code=entry.legacy_code
        )
        if not sku_doc:
            results["not_found"].append(lookup_key)
            continue

        sku_id = sku_doc.get("id")
        if not sku_id or not store_id:
            results["errors"].append({"entry": entry.model_dump(), "error": "sku missing id/store_id"})
            continue

        price_incl = Decimal(str(entry.retail_price)).quantize(Decimal("0.01"))
        price_excl = (price_incl / (Decimal("1") + _GST_RATE)).quantize(Decimal("0.01"))

        existing_id, existing = _find_active_price(
            fs_db, store_id=store_id, sku_id=sku_id, today_iso=today_iso
        )
        if existing:
            fs_db.collection(f"stores/{store_id}/prices").document(existing_id).update({
                "price_incl_tax": float(price_incl),
                "price_excl_tax": float(price_excl),
                "updated_at": now_iso,
            })
            results["updated"] += 1
        else:
            new_id = str(uuid.uuid4())
            fs_db.collection(f"stores/{store_id}/prices").document(new_id).set({
                "id": new_id,
                "sku_id": sku_id,
                "store_id": store_id,
                "price_incl_tax": float(price_incl),
                "price_excl_tax": float(price_excl),
                "price_unit": 1,
                "valid_from": today_iso,
                "valid_to": _FAR_FUTURE.isoformat(),
                "created_at": now_iso,
                "updated_at": now_iso,
            })
            results["created"] += 1

    total = results["updated"] + results["created"]
    results["message"] = (
        f"Saved {total} prices "
        f"({results['updated']} updated, {results['created']} new). "
        f"{len(results['not_found'])} SKUs not found."
    )
    return results


@router.get("/exports/nec-jewel")
async def export_nec_jewel(
    brand: str = Query(BRAND_NAME),
    store_code: str | None = Query(None, alias="store"),
    inv_store_code: str = Query(DEFAULT_INV_STORE_CODE, alias="inv_store"),
    include_drafts: bool = Query(False),
    fs_db: FirestoreClient = Depends(get_firestore_db),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> StreamingResponse:
    normalized_store_code = canonicalize_store_code_input(store_code)
    normalized_inv_store_code = canonicalize_store_code_input(inv_store_code) or DEFAULT_INV_STORE_CODE
    products, _excluded = fetch_sellable_skus_from_firestore(
        fs_db,
        brand_name=brand,
        store_code=normalized_store_code,
        inv_store_code=normalized_inv_store_code,
        include_drafts=include_drafts,
    )

    if not products:
        raise HTTPException(
            status_code=404,
            detail="No sellable products are ready for Jewel NEC POS export.",
        )

    filename = default_export_filename()
    workbook = build_workbook_bytes(products)
    return StreamingResponse(
        BytesIO(workbook),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
