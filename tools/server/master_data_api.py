#!/usr/bin/env python3
"""
Local master-data API for the price-entry workflow.

Reads/writes data/master_product_list.json directly. No cloud, no auth --
listens on the LAN so the iPad on the same WiFi can reach it. Run on the
shop's Mac:

    python tools/server/master_data_api.py

Browser:
    http://localhost:8765/

iPad/macOS app: configure base URL as displayed in the startup banner.

Endpoints:
    GET   /api/health
    GET   /api/stats
    GET   /api/products?launch_only=true&needs_price=true&supplier=CN-001
    PATCH /api/products/{sku}           body: partial fields
    POST  /api/export/nec_jewel         regenerates the Excel
    GET   /api/exports/{filename}       downloads a generated file
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_JSON = REPO_ROOT / "data" / "master_product_list.json"
EXPORT_DIR = REPO_ROOT / "data" / "exports"
UPLOAD_DIR = REPO_ROOT / "data" / "uploads" / "invoices"
EXPORT_SCRIPT = REPO_ROOT / "tools" / "scripts" / "export_nec_jewel.py"
LABELS_EXPORT_SCRIPT = REPO_ROOT / "tools" / "scripts" / "export_labels.py"

# Make tools/scripts importable so we can reuse identifier_utils + the
# entry-shaping helpers that add_hengwei_skus_to_master.py uses today.
sys.path.insert(0, str(REPO_ROOT / "tools" / "scripts"))

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_master() -> dict[str, Any]:
    return json.loads(MASTER_JSON.read_text(encoding="utf-8"))


def _atomic_write_master(data: dict[str, Any]) -> None:
    backup = MASTER_JSON.with_suffix(MASTER_JSON.suffix + ".bak")
    backup.write_bytes(MASTER_JSON.read_bytes())
    tmp = MASTER_JSON.with_suffix(MASTER_JSON.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, MASTER_JSON)


async def _persist_invoice_artifacts(
    *,
    upload_id: str,
    original_bytes: bytes,
    content_type: str,
    extracted: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Persist OCR inputs/results to GCS when configured.

    The OCR pipeline still needs a real file path while it runs, but durable
    storage should be the project bucket, not ``data/uploads`` on the app host.
    Local standalone runs without GCP credentials continue to work.
    """
    if not os.environ.get("AI_GCS_BUCKET") and not os.environ.get("GCP_PROJECT_ID"):
        return {}

    try:
        from app.services.gcs import upload_bytes
    except Exception:
        return {}

    uris: dict[str, str] = {}
    original_path = f"master-data/invoices/{upload_id}/source"
    uris["source_gcs_uri"] = await upload_bytes(
        original_bytes,
        original_path,
        content_type or "application/octet-stream",
    )
    if extracted is not None:
        raw = json.dumps(extracted, indent=2, ensure_ascii=False).encode("utf-8")
        uris["ocr_gcs_uri"] = await upload_bytes(
            raw,
            f"master-data/invoices/{upload_id}/ocr.json",
            "application/json",
        )
    return uris


class ProductPatch(BaseModel):
    retail_price: Optional[float] = Field(default=None, gt=0)
    sale_ready: Optional[bool] = None
    block_sales: Optional[bool] = None
    description: Optional[str] = None
    long_description: Optional[str] = None
    qty_on_hand: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    stocking_location: Optional[str] = None


def _is_purchased(p: dict) -> bool:
    """A product counts as 'purchased' only if we have a concrete PO/invoice
    on file for it.

    NOTE: inventory_type='purchased' is too broad — it tags historical
    Takashimaya sales rows (sources=['sales_taka']) which we did not
    necessarily restock for Jewel Changi. The signal we actually want is
    'there is an order or invoice document linking to this SKU', which is
    source_orders[] (set by add_hengwei_skus_to_master.py) or a sources entry
    matching *_order_* / *_invoice_* (set by the OCR ingest endpoint)."""
    if p.get("source_orders"):
        return True
    for s in p.get("sources") or []:
        s = str(s)
        if "_order_" in s or "_invoice_" in s:
            return True
    return False


def _matches_filters(
    p: dict,
    launch_only: bool,
    needs_price: bool,
    supplier: Optional[str],
    purchased_only: bool,
    sourcing_strategy: Optional[str] = None,
) -> bool:
    if supplier and (p.get("supplier_id") or "") != supplier:
        return False
    if sourcing_strategy:
        if sourcing_strategy == "manufactured":
            if not str(p.get("sourcing_strategy") or "").startswith("manufactured"):
                return False
        elif (p.get("sourcing_strategy") or "") != sourcing_strategy:
            return False
    has_price = bool(p.get("retail_price") or p.get("price_incl_tax"))
    if needs_price and has_price:
        return False
    if launch_only:
        if not (p.get("sale_ready") or p.get("needs_retail_price")):
            return False
    if purchased_only and not _is_purchased(p):
        return False
    return True


app = FastAPI(title="RetailSG Master Data Editor", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\.|192\.168\.|172\.\d+\.).*",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "master_json": str(MASTER_JSON),
        "master_exists": MASTER_JSON.exists(),
        "now": _now(),
    }


@app.get("/api/stats")
def stats() -> dict:
    data = _read_master()
    products = data.get("products", [])
    by_supplier: dict[str, int] = {}
    sale_ready = 0
    needs_price = 0
    needs_review = 0
    missing_price_in_sale_ready = 0
    for p in products:
        sup = p.get("supplier_id") or "(none)"
        by_supplier[sup] = by_supplier.get(sup, 0) + 1
        has_price = bool(p.get("retail_price") or p.get("price_incl_tax"))
        if p.get("sale_ready"):
            sale_ready += 1
            if not has_price:
                missing_price_in_sale_ready += 1
        if p.get("needs_retail_price"):
            needs_price += 1
        if p.get("needs_review"):
            needs_review += 1
    return {
        "total": len(products),
        "sale_ready": sale_ready,
        "needs_price_flag": needs_price,
        "needs_review_flag": needs_review,
        "sale_ready_missing_price": missing_price_in_sale_ready,
        "by_supplier": by_supplier,
    }


@app.get("/api/products")
def list_products(
    launch_only: bool = Query(True, description="Only sale_ready or needs_retail_price products"),
    needs_price: bool = Query(False, description="Only those without a retail_price"),
    supplier: Optional[str] = Query(None),
    purchased_only: bool = Query(True, description="Only products from real POs/invoices (skip catalog-only rows)"),
    sourcing_strategy: Optional[str] = Query(None, description="Filter by sourcing_strategy. Pass 'manufactured' to match any manufactured_* value."),
    group_variants: bool = Query(False, description="Populate variant_siblings on family heads when true."),
) -> dict:
    data = _read_master()
    products = data.get("products", [])
    rows = [
        p for p in products
        if _matches_filters(p, launch_only, needs_price, supplier, purchased_only, sourcing_strategy)
    ]
    rows.sort(key=lambda p: ((p.get("supplier_id") or "zzz"), (p.get("product_type") or ""), (p.get("sku_code") or "")))
    if group_variants:
        by_group: dict[str, list[dict[str, Any]]] = {}
        for p in rows:
            group_id = p.get("variant_group_id")
            if group_id:
                by_group.setdefault(str(group_id), []).append(p)
        grouped_rows: list[dict[str, Any]] = []
        consumed: set[str] = set()
        for p in rows:
            sku = str(p.get("sku_code") or "")
            group_id = p.get("variant_group_id")
            if not group_id:
                grouped_rows.append(p)
                continue
            family = by_group.get(str(group_id), [])
            head = family[0] if family else p
            head_sku = str(head.get("sku_code") or "")
            if sku != head_sku or head_sku in consumed:
                continue
            clone = dict(head)
            clone["variant_siblings"] = [dict(sib) for sib in family[1:]]
            grouped_rows.append(clone)
            consumed.add(head_sku)
        rows = grouped_rows
    return {"count": len(rows), "products": rows}


@app.get("/api/products/{sku}")
def get_product(sku: str) -> dict:
    data = _read_master()
    for p in data.get("products", []):
        if (p.get("sku_code") or "") == sku:
            return p
    raise HTTPException(status_code=404, detail=f"sku_code {sku} not found")


@app.patch("/api/products/{sku}")
def patch_product(sku: str, patch: ProductPatch) -> dict:
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="empty patch")

    with _lock:
        data = _read_master()
        target = None
        for p in data.get("products", []):
            if (p.get("sku_code") or "") == sku:
                target = p
                break
        if target is None:
            raise HTTPException(status_code=404, detail=f"sku_code {sku} not found")

        notes = updates.pop("notes", None)
        if notes is not None:
            target["retail_price_note"] = notes
        target.update(updates)

        if "retail_price" in updates:
            target["retail_price_set_at"] = _now()
        if updates.get("sale_ready") is True:
            target.pop("needs_retail_price", None)
            target.pop("needs_review", None)

        target["last_modified_at"] = _now()
        target["last_modified_via"] = "master_data_api"

        meta = data.setdefault("metadata", {})
        meta["last_modified"] = _now()
        meta["last_modified_by"] = "master_data_api"
        _atomic_write_master(data)

    return target


@app.post("/api/export/nec_jewel")
def export_nec_jewel(store: str = "JEWEL-01") -> dict:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = EXPORT_DIR / "nec_jewel_master_data.xlsx"
    cmd = [sys.executable, str(EXPORT_SCRIPT), "--from-json", "--output", str(output)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "output_path": str(output) if output.exists() else None,
        "download_url": f"/api/exports/{output.name}" if output.exists() else None,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
    }


class ExportLabelsRequest(BaseModel):
    skus: list[str] = Field(default_factory=list, description="SKU codes to include. Empty = all sale-ready products with a PLU.")
    output_name: Optional[str] = Field(default=None, description="Override output filename (must end in .xlsx).")
    include_box: bool = Field(default=True, description="Include the BoxLabels sheet (storage/drawer tags). Set false for item-only labels.")


def export_labels(req: ExportLabelsRequest) -> dict:
    """Generate a Brother P-touch XLSX for a chosen set of SKU codes.

    Reads master JSON to map sku_code -> nec_plu, then invokes
    tools/scripts/export_labels.py --from-json --only-plus <plu,plu,...>.
    Mirrors the export_nec_jewel() return shape so the frontend can reuse the
    same download flow."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    data = _read_master()
    products = data.get("products", [])
    by_sku = {(p.get("sku_code") or ""): p for p in products}

    plus_codes: list[str] = []
    missing_skus: list[str] = []
    skus_no_plu: list[str] = []
    for sku in req.skus:
        prod = by_sku.get(sku)
        if not prod:
            missing_skus.append(sku)
            continue
        plu = prod.get("nec_plu") or prod.get("plu_code")
        if not plu:
            skus_no_plu.append(sku)
            continue
        plus_codes.append(str(plu))

    output_name = req.output_name or "ptouch_labels.xlsx"
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.xlsx", output_name):
        raise HTTPException(status_code=400, detail="output_name must match [A-Za-z0-9._-]+.xlsx")
    output = EXPORT_DIR / output_name

    cmd = [sys.executable, str(LABELS_EXPORT_SCRIPT), "--from-json", "--output", str(output)]
    if not req.include_box:
        cmd.append("--no-box")
    if plus_codes:
        cmd += ["--only-plus", ",".join(plus_codes)]
    elif req.skus:
        return {
            "ok": False,
            "exit_code": -1,
            "output_path": None,
            "download_url": None,
            "stdout": "",
            "stderr": f"None of the requested SKUs have a PLU. missing_skus={missing_skus} skus_no_plu={skus_no_plu}",
            "missing_skus": missing_skus,
            "skus_no_plu": skus_no_plu,
            "plu_count": 0,
        }

    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    return {
        "ok": proc.returncode == 0 and output.exists(),
        "exit_code": proc.returncode,
        "output_path": str(output) if output.exists() else None,
        "download_url": f"/api/exports/{output.name}" if output.exists() else None,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
        "missing_skus": missing_skus,
        "skus_no_plu": skus_no_plu,
        "plu_count": len(plus_codes),
    }


@app.post("/api/export/labels")
def export_labels_endpoint(req: ExportLabelsRequest) -> dict:
    return export_labels(req)


@app.get("/api/exports/{filename}")
def download_export(filename: str) -> FileResponse:
    safe = (EXPORT_DIR / filename).resolve()
    if not str(safe).startswith(str(EXPORT_DIR.resolve())) or not safe.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(safe), filename=filename)


# ── Invoice ingest (DeepSeek OCR → preview → commit) ─────────────────────────
#
# Two-step so the user can review OCR output before it touches the master JSON:
#   1. POST /api/ingest/invoice         → upload file, run OCR, return preview
#   2. POST /api/ingest/invoice/commit  → write reviewed entries to master JSON
#
# OCR uses tools/scripts/supplier_ocr_pipeline.py's deepseek-vision mode
# (PyMuPDF text layer → deepseek-reasoner clean-up → deepseek-chat JSON).
# Entry shape mirrors add_hengwei_skus_to_master.py so downstream NEC export
# treats new rows identically to manually added ones.

# OCR returns clean English product types — map straight to the existing
# 3-char SKU type code. Anything not on this list falls through to
# detect_product_type() (size-based bookend heuristic etc.).
_OCR_TYPE_TO_ABBR: dict[str, tuple[str, str]] = {
    "bookend": ("BKE", "Bookend"),
    "napkin holder": ("NAP", "Napkin Holder"),
    "decorative object": ("DEC", "Decorative Object"),
    "sculpture": ("DEC", "Sculpture"),
    "figurine": ("DEC", "Figurine"),
    "vase": ("DEC", "Vase"),
    "bowl": ("DEC", "Bowl"),
    "tray": ("DEC", "Tray"),
    "box": ("DEC", "Box"),
    "bracelet": ("BRC", "Bracelet"),
    "necklace": ("NEC", "Necklace"),
    "ring": ("RNG", "Ring"),
    "pendant": ("PND", "Pendant"),
    "earring": ("EAR", "Earring"),
    "charm": ("CHM", "Charm"),
}


class IngestPreviewItem(BaseModel):
    line_number: Optional[int] = None
    supplier_item_code: Optional[str] = None
    product_name_en: Optional[str] = None
    material: Optional[str] = None
    product_type: Optional[str] = None
    size: Optional[str] = None
    quantity: Optional[int] = None
    unit_price_cny: Optional[float] = None
    proposed_sku: Optional[str] = None
    proposed_plu: Optional[str] = None
    proposed_cost_sgd: Optional[float] = None
    already_exists: bool = False
    existing_sku: Optional[str] = None
    skip_reason: Optional[str] = None


class IngestCommitRequest(BaseModel):
    upload_id: str
    items: list[dict] = Field(default_factory=list)
    supplier_id: str = "CN-001"
    supplier_name: str = "Hengwei Craft"
    order_number: Optional[str] = None


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return base or "upload"


def _ocr_to_preview(
    extracted: dict,
    upload_id: str,
    products: list[dict],
) -> dict:
    """Turn the OCR JSON into a list of preview entries with proposed SKU/PLU."""
    from identifier_utils import allocate_identifier_pair, max_sku_sequence
    from add_hengwei_skus_to_master import (
        FX_CNY_PER_SGD,
        detect_material,
        detect_product_type,
    )

    sku_set = {str(p["sku_code"]).strip() for p in products if p.get("sku_code")}
    plu_set: set[str] = set()
    for p in products:
        for f in ("nec_plu", "plu_code"):
            v = p.get(f)
            if v:
                plu_set.add(str(v).strip())
    have_codes = {str(p["internal_code"]).strip() for p in products if p.get("internal_code")}
    by_code = {str(p["internal_code"]).strip(): p for p in products if p.get("internal_code")}
    next_seq = max(max_sku_sequence(sku_set), 0) + 1

    items_out: list[dict] = []
    for raw in extracted.get("items", []):
        code = raw.get("supplier_item_code")
        material_desc = raw.get("material") or ""
        product_type_text = (raw.get("product_type") or "").strip().lower()
        size = raw.get("size") or ""
        note = raw.get("notes") or raw.get("product_name_en") or ""
        unit_price = raw.get("unit_price")
        currency = (extracted.get("currency") or "CNY").upper()
        unit_price_cny = float(unit_price) if (unit_price and currency == "CNY") else None
        cost_sgd = round(unit_price_cny / FX_CNY_PER_SGD, 2) if unit_price_cny else None

        item = {
            "line_number": raw.get("line_number"),
            "supplier_item_code": code,
            "product_name_en": raw.get("product_name_en"),
            "material": material_desc,
            "product_type": raw.get("product_type"),
            "size": size,
            "quantity": raw.get("quantity"),
            "unit_price_cny": unit_price_cny,
            "proposed_cost_sgd": cost_sgd,
            "already_exists": False,
            "existing_sku": None,
            "proposed_sku": None,
            "proposed_plu": None,
            "skip_reason": None,
        }

        if not code:
            item["skip_reason"] = "no supplier_item_code (manual line — add by hand)"
            items_out.append(item)
            continue

        if code in have_codes:
            existing = by_code[code]
            item["already_exists"] = True
            item["existing_sku"] = existing.get("sku_code")
            item["proposed_sku"] = existing.get("sku_code")
            item["proposed_plu"] = existing.get("nec_plu")
            items_out.append(item)
            continue

        # Allocate fresh SKU+PLU. Type detection: prefer OCR's clean English
        # type, fall back to the size-based heuristic in add_hengwei_skus_to_master.
        type_hit = _OCR_TYPE_TO_ABBR.get(product_type_text)
        if type_hit:
            type_abbr, _type_label = type_hit
        else:
            type_abbr, _type_slug, _type_label = detect_product_type(size, material_desc, note)

        mat_abbr, _mat_label = detect_material(material_desc)

        def _sku_factory(seq: int, _ta=type_abbr, _ma=mat_abbr) -> str:
            return f"VE{_ta}{_ma}{seq:07d}"

        sku_code, plu_code, next_seq = allocate_identifier_pair(
            _sku_factory, sku_set, plu_set, next_seq
        )
        sku_set.add(sku_code)
        plu_set.add(plu_code)

        item["proposed_sku"] = sku_code
        item["proposed_plu"] = plu_code
        items_out.append(item)

    return {
        "upload_id": upload_id,
        "document_type": extracted.get("document_type"),
        "document_number": extracted.get("document_number"),
        "document_date": extracted.get("document_date"),
        "supplier_name": extracted.get("supplier_name"),
        "currency": extracted.get("currency"),
        "document_total": extracted.get("document_total"),
        "items": items_out,
        "summary": {
            "total_lines": len(items_out),
            "new_skus": sum(1 for i in items_out if i["proposed_sku"] and not i["already_exists"] and not i["skip_reason"]),
            "already_exists": sum(1 for i in items_out if i["already_exists"]),
            "skipped": sum(1 for i in items_out if i["skip_reason"]),
        },
    }


@app.post("/api/ingest/invoice")
async def ingest_invoice(file: UploadFile = File(...)) -> dict:
    """Upload a supplier PDF/image, run DeepSeek OCR, return a preview.
    Nothing is written to master_product_list.json yet — call /api/ingest/invoice/commit
    with the (possibly edited) item list after the user reviews."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="DEEPSEEK_API_KEY not set on the server. Export it before starting master_data_api.py.",
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    upload_id = f"{stamp}-{_safe_filename(file.filename or 'upload')}"
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    content_type = file.content_type or "application/octet-stream"
    artifact_uris = await _persist_invoice_artifacts(
        upload_id=upload_id,
        original_bytes=contents,
        content_type=content_type,
    )

    try:
        from supplier_ocr_pipeline import extract_with_deepseek_local
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"OCR pipeline import failed: {exc}",
        )

    suffix = Path(file.filename or upload_id).suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="retailsg-invoice-ocr-") as tmpdir:
        saved_path = Path(tmpdir) / f"source{suffix}"
        saved_path.write_bytes(contents)
        try:
            extracted = extract_with_deepseek_local(
                document_name=file.filename or upload_id,
                file_path=saved_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"OCR failed: {exc}")

    artifact_uris.update(
        await _persist_invoice_artifacts(
            upload_id=upload_id,
            original_bytes=contents,
            content_type=content_type,
            extracted=extracted,
        )
    )

    data = _read_master()
    preview = _ocr_to_preview(extracted, upload_id=upload_id, products=data.get("products", []))
    if artifact_uris:
        preview["artifact_uris"] = artifact_uris
    return preview


@app.post("/api/ingest/invoice/commit")
def commit_invoice(req: IngestCommitRequest) -> dict:
    """Append the reviewed items to master_product_list.json, mirroring the
    shape add_hengwei_skus_to_master.py writes."""
    from identifier_utils import aligned_nec_plu_for_sku
    from add_hengwei_skus_to_master import (
        FX_CNY_PER_SGD,
        STOCKING_LOCATION,
        detect_material,
        detect_product_type,
        synth_description,
        synth_long_description,
    )

    if not req.items:
        raise HTTPException(status_code=400, detail="no items to commit")

    with _lock:
        data = _read_master()
        products = data.setdefault("products", [])
        existing_codes = {str(p["internal_code"]).strip() for p in products if p.get("internal_code")}
        existing_skus = {str(p["sku_code"]).strip() for p in products if p.get("sku_code")}

        added: list[dict] = []
        skipped: list[dict] = []
        for item in req.items:
            code = item.get("supplier_item_code")
            sku = item.get("proposed_sku")
            plu = item.get("proposed_plu")
            if not code or not sku or not plu:
                skipped.append({"item": item, "reason": "missing code/sku/plu"})
                continue
            if code in existing_codes or sku in existing_skus:
                skipped.append({"item": item, "reason": "already exists"})
                continue
            if aligned_nec_plu_for_sku(sku) != plu:
                skipped.append({"item": item, "reason": f"PLU/SKU misaligned: {sku}/{plu}"})
                continue

            material_desc = item.get("material") or ""
            note = item.get("product_name_en") or ""
            size = item.get("size") or ""
            mat_abbr, mat_label = detect_material(material_desc)
            ocr_type_text = (item.get("product_type") or "").strip().lower()
            type_hit = _OCR_TYPE_TO_ABBR.get(ocr_type_text)
            if type_hit:
                _ta, type_label = type_hit
            else:
                _ta, _ts, type_label = detect_product_type(size, material_desc, note)

            unit_price_cny = item.get("unit_price_cny")
            cost_sgd = round(unit_price_cny / FX_CNY_PER_SGD, 2) if unit_price_cny else None

            entry = {
                "id": f"{req.supplier_id.lower()}-{code.lower()}",
                "internal_code": code,
                "sku_code": sku,
                "description": synth_description(type_label, mat_label, size, code),
                "long_description": synth_long_description(type_label, mat_label, size, material_desc),
                "material": mat_label,
                "product_type": type_label,
                "category": "Home Decor",
                "amazon_sku": f"VE-{mat_abbr}-{sku[2:5]}-{code}",
                "google_product_id": f"online:en:SG:{sku}",
                "google_product_category": "Home & Garden > Decor",
                "nec_plu": plu,
                "cost_price": cost_sgd,
                "cost_currency": "SGD" if cost_sgd is not None else None,
                "cost_basis": (
                    {
                        "source_currency": "CNY",
                        "source_amount": unit_price_cny,
                        "fx_rate_cny_per_sgd": FX_CNY_PER_SGD,
                    }
                    if unit_price_cny
                    else None
                ),
                "retail_price": None,
                "qty_on_hand": item.get("quantity"),
                "supplier_id": req.supplier_id,
                "supplier_name": req.supplier_name,
                "supplier_item_code": code,
                "source_orders": [req.order_number] if req.order_number else [],
                "sources": [f"{req.supplier_id.lower()}_invoice_{req.upload_id}"],
                "raw_names": [item.get("product_name_en")] if item.get("product_name_en") else [],
                "mention_count": 1,
                "inventory_type": "purchased",
                "sourcing_strategy": "supplier_premade",
                "inventory_category": "finished_for_sale",
                "sale_ready": False,
                "block_sales": False,
                "stocking_status": "in_stock",
                "stocking_location": STOCKING_LOCATION,
                "use_stock": True,
                "size": size,
                "added_at": _now(),
                "added_via": f"master_data_api/ingest_invoice/{req.upload_id}",
                "needs_review": True,
                "needs_retail_price": True,
            }
            products.append(entry)
            existing_codes.add(code)
            existing_skus.add(sku)
            added.append(entry)

        if added:
            meta = data.setdefault("metadata", {})
            meta["last_modified"] = _now()
            meta["last_modified_by"] = "master_data_api/ingest_invoice"
            _atomic_write_master(data)

    return {
        "added": len(added),
        "skipped": len(skipped),
        "added_entries": added,
        "skipped_entries": skipped,
    }


# ── Manual product create (no invoice) ────────────────────────────────────────
#
# Companion to /api/ingest/invoice/commit for the case where a staff member
# wants to add a one-off SKU without a supplier document — e.g. a hand-made
# piece, a gift item, or a SKU from a supplier that doesn't issue invoices.
# Mirrors the entry shape commit_invoice() writes so downstream NEC export and
# Firestore publish-price treat manual rows identically to OCR'd ones.

# Reverse lookup: human label → (3-char abbrev, label) for the same set of
# product types the OCR ingest understands. Built off _OCR_TYPE_TO_ABBR so we
# never drift between manual and OCR entries.
_TYPE_LABEL_TO_ABBR: dict[str, tuple[str, str]] = {
    label.lower(): (abbr, label) for abbr, label in _OCR_TYPE_TO_ABBR.values()
}


# ── Sourcing-origin taxonomy (server-owned) ──────────────────────────────────
#
# The frontend renders these as the inventory-creation origin choices. Adding
# a new value here automatically surfaces it in the staff-portal modal, which
# is why the list lives on the server rather than being hardcoded client-side.
#
# `inventory_type` is the implied default for downstream stock accounting:
# "purchased" rows count as bought-in, "finished" rows as in-house assembled.
_SOURCING_OPTIONS: list[dict[str, Any]] = [
    {
        "value": "manufactured_in_house",
        "label": "Manufactured by Victoria Enso",
        "description": "Built in our workshop from raw materials we hold.",
        "requires_supplier": False,
        "inventory_type": "finished",
    },
    {
        "value": "supplier_premade",
        "label": "Bought from supplier (as-is)",
        "description": "Purchased finished from a supplier with no modification.",
        "requires_supplier": True,
        "inventory_type": "purchased",
    },
    {
        "value": "supplier_modified",
        "label": "Bought from supplier, then modified in-house",
        "description": "Sourced from a supplier and finished/assembled by us.",
        "requires_supplier": True,
        "inventory_type": "finished",
    },
]
_SOURCING_OPTIONS_BY_VALUE: dict[str, dict[str, Any]] = {
    o["value"]: o for o in _SOURCING_OPTIONS
}


def list_sourcing_options() -> dict[str, Any]:
    return {"options": _SOURCING_OPTIONS}


@app.get("/api/sourcing-options")
def sourcing_options_endpoint() -> dict[str, Any]:
    return list_sourcing_options()


# ── Supplier catalog (read + extend on the fly) ──────────────────────────────
#
# Each `docs/suppliers/<slug>/catalog_products.json` is a structured snapshot
# of the supplier's price list. The manual-create flow lets staff browse it
# when picking a supplier-sourced item, and append a new entry when the row
# they're about to create isn't there yet.

_SUPPLIERS_DIR = REPO_ROOT / "docs" / "suppliers"


def _supplier_catalog_path(slug: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "", slug)
    if not safe:
        raise HTTPException(status_code=400, detail="invalid supplier slug")
    return _SUPPLIERS_DIR / safe / "catalog_products.json"


def _load_supplier_catalog(slug: str) -> dict[str, Any]:
    path = _supplier_catalog_path(slug)
    if not path.exists():
        return {
            "schema_version": 1,
            "supplier_id": None,
            "supplier_name": None,
            "catalog_sources": [],
            "products": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def list_suppliers() -> dict[str, Any]:
    """Scan docs/suppliers/* for any folder that has a catalog_products.json
    and surface the (supplier_id, supplier_name, slug, product_count) tuple."""
    suppliers: list[dict[str, Any]] = []
    if not _SUPPLIERS_DIR.exists():
        return {"suppliers": suppliers}
    for child in sorted(_SUPPLIERS_DIR.iterdir()):
        if not child.is_dir():
            continue
        catalog_path = child / "catalog_products.json"
        if not catalog_path.exists():
            # Surface even un-structured supplier folders so staff can pick
            # them — they just won't have a browsable catalog yet.
            suppliers.append(
                {
                    "slug": child.name,
                    "supplier_id": None,
                    "supplier_name": child.name.replace("_", " ").title(),
                    "product_count": 0,
                    "has_catalog": False,
                }
            )
            continue
        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        suppliers.append(
            {
                "slug": child.name,
                "supplier_id": data.get("supplier_id"),
                "supplier_name": data.get("supplier_name") or child.name,
                "product_count": len(data.get("products", []) or []),
                "has_catalog": True,
            }
        )
    return {"suppliers": suppliers}


@app.get("/api/suppliers")
def suppliers_endpoint() -> dict[str, Any]:
    return list_suppliers()


def list_supplier_catalog(
    slug: str,
    *,
    query: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    data = _load_supplier_catalog(slug)
    products = list(data.get("products", []) or [])
    if query:
        q = query.lower().strip()
        if q:
            def _hit(p: dict[str, Any]) -> bool:
                hay = " ".join(
                    str(p.get(k) or "")
                    for k in (
                        "primary_supplier_item_code",
                        "raw_model",
                        "display_name",
                        "materials",
                        "size",
                        "color",
                    )
                ).lower()
                if q in hay:
                    return True
                for code in p.get("supplier_item_codes", []) or []:
                    if q in str(code).lower():
                        return True
                return False

            products = [p for p in products if _hit(p)]
    products = products[: max(0, min(limit, 200))]
    return {
        "slug": slug,
        "supplier_id": data.get("supplier_id"),
        "supplier_name": data.get("supplier_name"),
        "count": len(products),
        "products": products,
    }


@app.get("/api/suppliers/{slug}/catalog")
def supplier_catalog_endpoint(
    slug: str,
    query: Optional[str] = Query(None, description="Free-text filter across code, model, materials, size."),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return list_supplier_catalog(slug, query=query, limit=limit)


class SupplierCatalogEntryAdd(BaseModel):
    """Body for appending a new entry to a supplier's catalog snapshot."""

    supplier_item_code: str = Field(min_length=1, max_length=64)
    display_name: Optional[str] = None
    materials: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    unit_price_cny: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None


def add_supplier_catalog_entry(
    slug: str,
    req: SupplierCatalogEntryAdd,
    *,
    created_by: str = "master_data_api",
) -> dict[str, Any]:
    path = _supplier_catalog_path(slug)
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    code = req.supplier_item_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="supplier_item_code required")

    with _lock:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {
                "schema_version": 1,
                "supplier_id": None,
                "supplier_name": slug.replace("_", " ").title(),
                "catalog_sources": [],
                "products": [],
            }
        products = data.setdefault("products", [])
        for p in products:
            if code in (p.get("supplier_item_codes") or []) or p.get("primary_supplier_item_code") == code:
                raise HTTPException(
                    status_code=409,
                    detail=f"supplier_item_code {code} already in {slug} catalog",
                )

        entry = {
            "catalog_product_id": f"{slug}:manual:{code}",
            "catalog_file": None,
            "sheet_name": None,
            "source_block_row": None,
            "source_value_column": None,
            "raw_model": code,
            "supplier_item_codes": [code],
            "primary_supplier_item_code": code,
            "display_name": (req.display_name or "").strip() or None,
            "size": (req.size or "").strip() or None,
            "materials": (req.materials or "").strip() or None,
            "color": (req.color or "").strip() or None,
            "price_label": "unit_price",
            "price_options_cny": [float(req.unit_price_cny)] if req.unit_price_cny is not None else [],
            "raw_price": str(req.unit_price_cny) if req.unit_price_cny is not None else None,
            "added_via": f"manual_create/{created_by}",
            "added_at": _now(),
            "notes": (req.notes or "").strip() or None,
        }
        products.append(entry)

        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    return entry


@app.post("/api/suppliers/{slug}/catalog")
def add_supplier_catalog_entry_endpoint(
    slug: str,
    req: SupplierCatalogEntryAdd,
) -> dict[str, Any]:
    return add_supplier_catalog_entry(slug, req)


# ── DeepSeek V3 description assist ───────────────────────────────────────────
#
# The staff portal calls this once the user has picked a product type, material,
# size and (optionally) a supplier-catalog hit. We ask DeepSeek-chat (V3) to
# draft a short retail-facing description + long description; the user is free
# to edit before saving. Falls back to the deterministic synth helpers when
# the AI gateway is unavailable so the create flow never blocks on it.

class AiDescribeProductRequest(BaseModel):
    product_type: str = Field(min_length=1)
    material: str = Field(min_length=1)
    size: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_item_code: Optional[str] = None
    supplier_catalog_hint: Optional[str] = Field(
        default=None,
        description="Free-text catalog row text (display_name, raw_model, color) to bias the AI.",
    )
    sourcing_strategy: Optional[str] = None


class AiDescribeProductResponse(BaseModel):
    description: str
    long_description: str
    is_fallback: bool
    model: Optional[str] = None


# Few-shot cache: load up to N rows from the master JSON the first time the
# AI describe endpoint runs, then reuse forever within the process. We
# deliberately skip rows whose long_description starts with our deterministic
# synth template ("crafted from") so we don't teach the model its own
# fallback voice — we want it to learn from the human-edited rows.
_FEW_SHOT_CACHE: list[dict[str, str]] | None = None


def _few_shot_describe_examples(n: int = 3) -> list[dict[str, str]]:
    global _FEW_SHOT_CACHE
    if _FEW_SHOT_CACHE is not None:
        return _FEW_SHOT_CACHE
    try:
        data = _read_master()
    except (OSError, json.JSONDecodeError):
        _FEW_SHOT_CACHE = []
        return _FEW_SHOT_CACHE
    buckets: dict[str, dict[str, str]] = {}
    for r in data.get("products", []) or []:
        desc = (r.get("description") or "").strip()
        long_desc = (r.get("long_description") or "").strip()
        if not desc or len(long_desc) < 80:
            continue
        # Skip our own synth-template output to avoid AI training on AI fallback.
        if "crafted from" in long_desc.lower() and "hand-finished" in long_desc.lower():
            continue
        sourcing = str(r.get("sourcing_strategy") or r.get("inventory_type") or "unknown")
        if sourcing.startswith("manufactured"):
            bucket = "manufactured"
        elif sourcing.startswith("supplier"):
            bucket = "supplier"
        else:
            bucket = "other"
        buckets.setdefault(bucket, {"description": desc[:120], "long_description": long_desc[:400]})
        if len(buckets) >= n:
            break
    _FEW_SHOT_CACHE = list(buckets.values())[:n]
    return _FEW_SHOT_CACHE


_FEW_SHOT_CACHE = _few_shot_describe_examples()


async def ai_describe_product(req: AiDescribeProductRequest) -> AiDescribeProductResponse:
    """Use DeepSeek V3 (chat) to draft retail copy for a new SKU."""
    from add_hengwei_skus_to_master import (
        detect_material,
        synth_description,
        synth_long_description,
    )

    type_label_input = req.product_type.strip()
    type_hit = _TYPE_LABEL_TO_ABBR.get(type_label_input.lower())
    type_label = type_hit[1] if type_hit else type_label_input
    _, mat_label = detect_material(req.material)
    size = req.size or ""

    fallback = AiDescribeProductResponse(
        description=synth_description(type_label, mat_label, size, req.supplier_item_code or "NEW"),
        long_description=synth_long_description(type_label, mat_label, size, req.material),
        is_fallback=True,
        model=None,
    )

    try:
        from app.services.ai_gateway import AIRequest, invoke
    except Exception:
        return fallback

    sourcing_label = ""
    if req.sourcing_strategy:
        opt = _SOURCING_OPTIONS_BY_VALUE.get(req.sourcing_strategy)
        if opt:
            sourcing_label = opt["label"]

    catalog_hint = (req.supplier_catalog_hint or "").strip()
    supplier_block = ""
    if req.supplier_name or req.supplier_item_code:
        supplier_block = (
            f"Supplier: {req.supplier_name or 'unspecified'}"
            + (f" (item code {req.supplier_item_code})" if req.supplier_item_code else "")
        )

    examples = _few_shot_describe_examples()
    examples_block = ""
    if examples:
        rendered: list[str] = []
        for ex in examples:
            rendered.append(
                "{"
                f'"description": {json.dumps(ex["description"])}, '
                f'"long_description": {json.dumps(ex["long_description"])}'
                "}"
            )
        examples_block = (
            "House style — three real rows we have shipped (match this voice):\n"
            + "\n".join(rendered)
            + "\n\n"
        )

    prompt = (
        "You write retail copy for Victoria Enso, a Singapore boutique selling "
        "stone/crystal home decor and gemstone jewellery. Voice: factual, calm, "
        "informative. British English spellings (colour, jewellery, finish). "
        "Never use marketing fluff like 'stunning', 'must-have', 'breathtaking'. "
        "When the piece is finished by us, end with the suffix 'Hand-finished.' When the "
        "raw material is imported, you may say 'Imported from China'. No emoji. "
        "No exclamation marks.\n\n"
        "Output JSON with two keys:\n"
        "  - description: max 110 chars, suitable for an in-store label and the "
        "POS screen. Lead with the product type and main material.\n"
        "  - long_description: 2-3 short sentences. Mention materials and "
        "dimensions plainly. Add one sentence of context about how the piece "
        "is finished or its intended use. No invented provenance or claims.\n\n"
        f"{examples_block}"
        "Now write copy for this row:\n"
        f"  Product type: {type_label}\n"
        f"  Material: {mat_label} (raw text from supplier: {req.material})\n"
        f"  Size: {size or 'unspecified'}\n"
        f"  Origin: {sourcing_label or req.sourcing_strategy or 'unspecified'}\n"
        f"  {supplier_block}\n"
        f"  Catalog hint: {catalog_hint or 'none'}\n\n"
        'Return ONLY a JSON object: {"description": "...", "long_description": "..."}'
    )

    ai_req = AIRequest(
        prompt=prompt,
        # DeepSeek's chat alias resolves to the latest DeepSeek-V3 checkpoint —
        # this is the model the user has standardised on for retail copy.
        # `deepseek-reasoner` (R1) is reserved for OCR clean-up where we want
        # chain-of-thought; for short structured copy V3 is faster and cheaper.
        model="deepseek-chat",
        purpose="master_data.describe_product",
        temperature=0.4,
        max_output_tokens=400,
        response_mime_type="application/json",
    )
    resp = await invoke(ai_req, fallback_text='{"error": "ai_unavailable"}')
    if resp.is_fallback:
        return fallback
    try:
        parsed = json.loads(resp.text)
        desc = str(parsed.get("description") or "").strip()
        long_desc = str(parsed.get("long_description") or "").strip()
    except (json.JSONDecodeError, TypeError):
        return fallback
    if not desc or not long_desc:
        return fallback
    return AiDescribeProductResponse(
        description=desc[:120],
        long_description=long_desc,
        is_fallback=False,
        model=resp.model,
    )


@app.post("/api/ai/describe_product")
async def ai_describe_product_endpoint(
    req: AiDescribeProductRequest,
) -> AiDescribeProductResponse:
    return await ai_describe_product(req)


class ManualProductCreateRequest(BaseModel):
    """Request body for the manual inventory-creation flow.

    SKU code and NEC PLU are **never** caller-supplied — they are always
    auto-allocated from the shared sequence so SKU/PLU pairs cannot drift.
    The legacy override fields were removed deliberately; do not re-add them.
    """

    description: str = Field(min_length=1, max_length=120)
    long_description: Optional[str] = None
    product_type: str = Field(min_length=1, description="Display label, e.g. 'Bookend'")
    material: str = Field(min_length=1, description="Display label or supplier text, e.g. 'Crystal'")
    size: Optional[str] = None
    supplier_id: Optional[str] = Field(
        default=None,
        description="Required when sourcing_strategy starts with 'supplier_'.",
    )
    supplier_name: Optional[str] = None
    supplier_item_code: Optional[str] = Field(
        default=None,
        description=(
            "Supplier's own catalog code (e.g. Hengwei 'A003A'). Optional but "
            "strongly recommended when sourcing from a supplier — links the row "
            "to the supplier catalog so re-orders auto-match."
        ),
    )
    internal_code: Optional[str] = Field(
        default=None,
        description="Internal/legacy code; auto-set to supplier_item_code when not given.",
    )
    cost_price: Optional[float] = Field(default=None, ge=0)
    cost_currency: Optional[str] = Field(default="SGD")
    qty_on_hand: Optional[int] = Field(default=None, ge=0)
    sourcing_strategy: str = Field(
        default="supplier_premade",
        description=(
            "Origin of the inventory. One of: manufactured_in_house, "
            "supplier_premade, supplier_modified. See list_sourcing_options()."
        ),
    )
    inventory_type: Optional[str] = Field(
        default=None,
        description="Auto-derived from sourcing_strategy when omitted.",
    )
    notes: Optional[str] = None
    image_urls: Optional[list[str]] = None
    variant_of_sku: Optional[str] = Field(
        default=None,
        description="When set, create this SKU as a variant of the existing parent SKU.",
    )
    variant_label: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Human label for this variant, e.g. 'Size M' or 'Black'.",
    )


def create_product(req: ManualProductCreateRequest, *, created_by: str = "master_data_api") -> dict:
    """Append a hand-entered SKU to master_product_list.json.

    Mirrors commit_invoice()'s entry shape so manual rows and OCR'd rows look
    identical to downstream tooling. SKU+PLU are **always** auto-allocated
    using the shared 7-digit sequence (see identifier_utils) — callers can
    never override them, which is why the legacy sku_code/nec_plu inputs were
    removed."""
    from identifier_utils import allocate_identifier_pair, max_sku_sequence
    from add_hengwei_skus_to_master import (
        STOCKING_LOCATION,
        detect_material,
        synth_description,
        synth_long_description,
    )

    description = req.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    sourcing = (req.sourcing_strategy or "").strip()
    sourcing_meta = _SOURCING_OPTIONS_BY_VALUE.get(sourcing)
    if sourcing_meta is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown sourcing_strategy '{sourcing}'. "
                f"Pick one of: {sorted(_SOURCING_OPTIONS_BY_VALUE.keys())}"
            ),
        )
    inventory_type = (req.inventory_type or sourcing_meta["inventory_type"]).strip()

    is_supplier_origin = sourcing.startswith("supplier_")
    supplier_id = (req.supplier_id or "").strip() or None
    if is_supplier_origin and not supplier_id and not req.variant_of_sku:
        raise HTTPException(
            status_code=400,
            detail="supplier_id is required when sourcing_strategy is supplier_*",
        )
    if not is_supplier_origin and not supplier_id:
        # In-house manufacture still tags the row to a supplier-of-record so
        # the existing UI filters keep working; default to the Victoria Enso
        # workshop pseudo-supplier.
        supplier_id = "VE-WORKSHOP"
    supplier_name = (req.supplier_name or "").strip() or (
        "Victoria Enso Workshop" if supplier_id == "VE-WORKSHOP" else None
    )

    type_label_input = req.product_type.strip()
    type_hit = _TYPE_LABEL_TO_ABBR.get(type_label_input.lower())
    if not type_hit:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown product_type '{type_label_input}'. "
                f"Pick one of: {sorted({lbl for _a, lbl in _TYPE_LABEL_TO_ABBR.values()})}"
            ),
        )
    type_abbr, type_label = type_hit

    material_input = req.material.strip()
    mat_abbr, mat_label = detect_material(material_input)

    with _lock:
        data = _read_master()
        products = data.setdefault("products", [])
        existing_skus = {str(p["sku_code"]).strip() for p in products if p.get("sku_code")}
        existing_codes = {str(p["internal_code"]).strip() for p in products if p.get("internal_code")}
        existing_plus: set[str] = set()
        for p in products:
            for f in ("nec_plu", "plu_code"):
                v = p.get(f)
                if v:
                    existing_plus.add(str(v).strip())

        variant_label = (req.variant_label or "").strip() or None
        variant_parent = None
        variant_group_id = None
        if req.variant_of_sku:
            parent_sku = req.variant_of_sku.strip()
            variant_parent = next(
                (p for p in products if str(p.get("sku_code") or "").strip() == parent_sku),
                None,
            )
            if not variant_parent:
                raise HTTPException(status_code=404, detail=f"variant_of_sku {parent_sku} not found")
            if not variant_label:
                raise HTTPException(status_code=400, detail="variant_label is required for variants")
            variant_group_id = str(variant_parent.get("variant_group_id") or uuid.uuid4())
            if not variant_parent.get("variant_group_id"):
                variant_parent["variant_group_id"] = variant_group_id

            supplier_id = (variant_parent.get("supplier_id") or supplier_id)
            supplier_name = (variant_parent.get("supplier_name") or supplier_name)
            type_label = variant_parent.get("product_type") or type_label
            material_input = variant_parent.get("material") or material_input
            inherited_type = _TYPE_LABEL_TO_ABBR.get(str(type_label).lower())
            if inherited_type:
                type_abbr, type_label = inherited_type
            mat_abbr, _ = detect_material(str(material_input))
            mat_label = variant_parent.get("material") or mat_label

        supplier_item_code = (req.supplier_item_code or "").strip() or None
        if variant_parent and not supplier_item_code:
            supplier_item_code = variant_parent.get("supplier_item_code") or variant_parent.get("internal_code")
        internal_code = (req.internal_code or "").strip() or supplier_item_code

        if internal_code and internal_code in existing_codes:
            raise HTTPException(
                status_code=409,
                detail=f"internal_code {internal_code} already exists",
            )

        next_seq = max(max_sku_sequence(existing_skus), 0) + 1

        def _sku_factory(seq: int, _ta=type_abbr, _ma=mat_abbr) -> str:
            return f"VE{_ta}{_ma}{seq:07d}"

        sku_code, plu_code, _next_seq = allocate_identifier_pair(
            _sku_factory, existing_skus, existing_plus, next_seq
        )

        size = req.size or ""
        if variant_parent:
            parent_desc = (variant_parent.get("description") or description).strip()
            description = f"{parent_desc} - {variant_label}"[:120]
            parent_long = (variant_parent.get("long_description") or "").strip()
            long_desc = f"{parent_long} Variant: {variant_label}.".strip() if parent_long else description
        else:
            long_desc = (
                req.long_description.strip()
                if req.long_description and req.long_description.strip()
                else synth_long_description(type_label, mat_label, size, material_input)
            )

        # Use the user's explicit description when present; only fall through
        # to the synth helper if they didn't supply one (the modal makes it
        # required, but the API accepts either).
        if not description:
            description = synth_description(type_label, mat_label, size, internal_code or sku_code)

        cost_price = float(req.cost_price) if req.cost_price is not None else None
        cost_currency = (req.cost_currency or ("SGD" if cost_price is not None else None))
        if cost_price is not None and cost_currency:
            cost_basis = {
                "source_currency": cost_currency,
                "source_amount": cost_price,
            }
        else:
            cost_basis = None

        entry_id_seed = (internal_code or sku_code).lower()
        entry = {
            "id": f"{supplier_id.lower()}-{entry_id_seed}",
            "internal_code": internal_code,
            "sku_code": sku_code,
            "description": description[:120],
            "long_description": long_desc,
            "material": mat_label,
            "product_type": type_label,
            "category": "Home Decor",
            "amazon_sku": f"VE-{mat_abbr}-{sku_code[2:5]}-{internal_code}" if internal_code else None,
            "google_product_id": f"online:en:SG:{sku_code}",
            "google_product_category": "Home & Garden > Decor",
            "nec_plu": plu_code,
            "cost_price": cost_price,
            "cost_currency": cost_currency,
            "cost_basis": cost_basis,
            "retail_price": None,
            "retail_price_note": req.notes,
            "qty_on_hand": req.qty_on_hand,
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "supplier_item_code": supplier_item_code or internal_code,
            "source_orders": [],
            "sources": [f"manual_entry:{created_by}"],
            "raw_names": [description],
            "mention_count": 1,
            "inventory_type": inventory_type,
            "sourcing_strategy": sourcing,
            "inventory_category": "finished_for_sale",
            "sale_ready": False,
            "block_sales": False,
            "stocking_status": "in_stock",
            "stocking_location": STOCKING_LOCATION,
            "use_stock": True,
            "size": size,
            "added_at": _now(),
            "added_via": f"master_data_api/manual_create/{created_by}",
            "needs_review": False,
            "needs_retail_price": True,
            "image_urls": list(req.image_urls or []),
        }
        if variant_group_id:
            entry["variant_group_id"] = variant_group_id
            entry["variant_label"] = variant_label
        products.append(entry)

        meta = data.setdefault("metadata", {})
        meta["last_modified"] = _now()
        meta["last_modified_by"] = f"master_data_api/manual_create/{created_by}"
        _atomic_write_master(data)

    return entry


@app.post("/api/products")
def create_product_endpoint(req: ManualProductCreateRequest) -> dict:
    """Standalone (LAN) endpoint for the manual create flow.

    The auth-protected backend exposes the same operation under
    /api/master-data/products via app/routers/master_data.py."""
    return create_product(req)


# ── AI price recommender (DeepSeek reasoner → chat) ──────────────────────────
#
# Treats the user's already-priced items as training data: for each unpriced
# SKU the reasoner picks the closest comparable(s), adapts their margin, and
# rounds to the nearest S$5. Cold-start fallback (few or zero priced items
# in a category) uses heuristic markups so the call is still useful on day 1.

_PRICE_RECOMMENDER_SCHEMA = {
    "type": "object",
    "properties": {
        "rules_inferred": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short rules derived from the priced examples (1 line each)."
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sku_code": {"type": "string"},
                    "recommended_retail_sgd": {"type": "number"},
                    "implied_margin_pct": {"type": "integer"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "comparable_skus": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                "required": ["sku_code", "recommended_retail_sgd", "confidence", "rationale"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["recommendations"],
}


class RecommendPricesRequest(BaseModel):
    target_skus: Optional[list[str]] = Field(
        default=None,
        description="Specific SKUs to price. Default: all unpriced purchased SKUs.",
    )
    max_targets: int = Field(default=80, ge=1, le=300)


def _compact_for_prompt(p: dict, include_retail: bool) -> dict:
    row: dict[str, Any] = {
        "sku": p.get("sku_code"),
        "type": p.get("product_type"),
        "material": p.get("material"),
        "size": p.get("size"),
        "cost_sgd": p.get("cost_price"),
    }
    if include_retail:
        retail = p.get("retail_price")
        row["retail_sgd"] = retail
        cost = p.get("cost_price")
        if retail and cost and retail > 0:
            row["margin_pct"] = round((retail - cost) / retail * 100)
    return row


@app.post("/api/ai/recommend_prices")
def recommend_prices(req: RecommendPricesRequest) -> dict:
    """Suggest retail prices for unpriced purchased SKUs using DeepSeek
    thinking mode. Returns recommendations the client previews before any
    PATCH is applied."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="DEEPSEEK_API_KEY not set on the server.",
        )

    data = _read_master()
    products = data.get("products", [])
    purchased = [p for p in products if _is_purchased(p)]

    priced = [
        p for p in purchased
        if p.get("retail_price") and p.get("cost_price")
    ]

    if req.target_skus:
        target_set = set(req.target_skus)
        targets = [p for p in purchased if p.get("sku_code") in target_set]
    else:
        targets = [
            p for p in purchased
            if not p.get("retail_price") and p.get("cost_price")
        ]

    targets = targets[: req.max_targets]
    if not targets:
        return {
            "rules_inferred": [],
            "recommendations": [],
            "notes": "Nothing to price — all purchased SKUs already have a retail_price.",
            "n_priced_examples": len(priced),
            "n_targets": 0,
        }

    priced_compact = [_compact_for_prompt(p, True) for p in priced]
    target_compact = [_compact_for_prompt(p, False) for p in targets]

    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")

    reasoner_prompt = (
        "You are a retail pricing analyst for a Singapore boutique selling Chinese crystal/stone "
        "home decor (bookends, decorative objects, napkin holders) at Jewel Changi Airport.\n"
        "Target customer: tourists and high-end locals. Baseline gross margin target: 60% "
        "(cost ÷ 0.4). Heavy/bulky items at high absolute price may drop to 50% to stay saleable; "
        "rare materials (malachite, fluorite, fine crystal) can hit 70%+. Round all retail prices "
        "to the nearest S$5.\n\n"
        f"PRICED ITEMS ({len(priced_compact)}) — treat these as ground truth set by the owner:\n"
        f"{json.dumps(priced_compact, indent=2, ensure_ascii=False)}\n\n"
        f"UNPRICED ITEMS ({len(target_compact)}) — recommend a retail_sgd for each:\n"
        f"{json.dumps(target_compact, indent=2, ensure_ascii=False)}\n\n"
        "For each unpriced item, identify the 1–3 most similar priced items (same type AND material first, "
        "then nearest size/cost), adapt their markup to this item, and round to the nearest S$5.\n"
        "If there are fewer than 3 comparable priced items in a category, use cold-start heuristics:\n"
        "  - Crystal / Stone decor under S$50 cost → 2.5x markup\n"
        "  - Crystal / Stone decor S$50–S$200 cost → 2.0x–2.2x markup\n"
        "  - Crystal / Stone decor over S$200 cost → 1.8x–2.0x markup\n"
        "  - Marble bookends → 2.2x\n"
        "  - Malachite / Fluorite (rarer) → 2.8x–3.0x\n"
        "  - Gypsum / mixed mineral → 2.3x\n"
        "And mark such items confidence='low'.\n\n"
        "Reason step-by-step in markdown — group your work by category. Do NOT generate JSON yet."
    )

    reasoner_resp = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[{"role": "user", "content": reasoner_prompt}],
        temperature=0.1,
        max_tokens=8192,
    )
    reasoned = reasoner_resp.choices[0].message.content or ""
    if "</think>" in reasoned:
        reasoned = reasoned.split("</think>", 1)[-1].strip()

    chat_prompt = (
        "Here is reasoning about retail price recommendations for a Singapore boutique:\n\n"
        f"{reasoned}\n\n"
        "Return ONLY valid JSON exactly matching this schema:\n"
        f"{json.dumps(_PRICE_RECOMMENDER_SCHEMA, indent=2)}\n\n"
        "Every unpriced SKU listed in the reasoning must appear in 'recommendations'. "
        "If you have low confidence, still return a price — just mark confidence='low'."
    )
    chat_resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": chat_prompt}],
        temperature=0.0,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )
    raw = chat_resp.choices[0].message.content or "{}"
    try:
        out = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"DeepSeek returned invalid JSON: {exc}")

    out["n_priced_examples"] = len(priced)
    out["n_targets"] = len(targets)
    return out


def _lan_ip() -> str:
    with contextlib.suppress(Exception):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    return "<unknown>"


def main() -> None:
    import uvicorn
    host = os.environ.get("MASTER_DATA_HOST", "0.0.0.0")
    port = int(os.environ.get("MASTER_DATA_PORT", "8765"))
    print("=" * 60)
    print("  RetailSG Master Data API")
    print("=" * 60)
    print(f"  Mac (this machine): http://localhost:{port}/api/health")
    print(f"  iPad/LAN:           http://{_lan_ip()}:{port}/api/health")
    print(f"  Master JSON:        {MASTER_JSON}")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
