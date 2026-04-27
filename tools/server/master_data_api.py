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
import threading
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
CATALOG_IMAGES_DIR = REPO_ROOT / "data" / "catalog" / "product_images"
CATALOG_EMBED_NPY = REPO_ROOT / "data" / "catalog" / "product_embeddings.npy"
CATALOG_EMBED_INDEX = REPO_ROOT / "data" / "catalog" / "product_embedding_index.json"

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
) -> bool:
    if supplier and (p.get("supplier_id") or "") != supplier:
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
) -> dict:
    data = _read_master()
    products = data.get("products", [])
    rows = [p for p in products if _matches_filters(p, launch_only, needs_price, supplier, purchased_only)]
    rows.sort(key=lambda p: ((p.get("supplier_id") or "zzz"), (p.get("product_type") or ""), (p.get("sku_code") or "")))
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
    image_url: Optional[str] = None
    image_match_confidence: Optional[str] = None  # "matched" | "page-fallback" | None


class IngestPreviewPageImage(BaseModel):
    page_number: int
    url: str


class IngestCommitRequest(BaseModel):
    upload_id: str
    items: list[dict] = Field(default_factory=list)
    supplier_id: str = "CN-001"
    supplier_name: str = "Hengwei Craft"
    order_number: Optional[str] = None


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return base or "upload"


def _extract_pdf_images(pdf_path: Path, upload_id: str) -> dict[str, Any]:
    """Pull every embedded image out of a supplier PDF and remember each
    image's Y-bbox so we can later pair it with the OCR'd line item that
    sits next to it on the page.

    Returns a dict with `image_dir`, `page_images` (URL list for the modal's
    fallback gallery), and `image_records` (raw bbox info consumed by
    `_match_codes_to_images`). Soft-fails to empty results if PyMuPDF is
    unavailable or the file isn't a PDF — the rest of ingest still works."""
    try:
        import fitz  # type: ignore
    except ImportError:
        return {"image_dir": None, "page_images": [], "image_records": []}

    image_dir = UPLOAD_DIR / f"{upload_id}_images"
    image_dir.mkdir(parents=True, exist_ok=True)

    page_images: list[dict] = []
    image_records: list[dict] = []

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return {"image_dir": image_dir, "page_images": [], "image_records": []}

    try:
        for page_idx in range(len(doc)):
            page = doc.load_page(page_idx)
            page_num = page_idx + 1
            for img_idx, img_info in enumerate(page.get_images(full=True)):
                xref = img_info[0]
                try:
                    bbox = page.get_image_bbox(img_info)
                except Exception:
                    bbox = None
                fname = f"page_{page_num:02d}_img_{img_idx:02d}.png"
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha > 3:  # CMYK → RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    pix.save(str(image_dir / fname))
                    pix = None
                except Exception:
                    continue
                image_records.append({
                    "page_number": page_num,
                    "filename": fname,
                    "y_top": float(bbox.y0) if bbox else None,
                    "y_bottom": float(bbox.y1) if bbox else None,
                })
                page_images.append({
                    "page_number": page_num,
                    "url": f"/api/uploads/{upload_id}_images/{fname}",
                })
    finally:
        doc.close()

    return {
        "image_dir": image_dir,
        "page_images": page_images,
        "image_records": image_records,
    }


def _match_codes_to_images(
    pdf_path: Path,
    upload_id: str,
    codes: list[str],
    image_records: list[dict],
) -> dict[str, str]:
    """For each supplier_item_code, find its Y-position via PDF text search
    and pick the closest embedded image on the same page. Returns a
    {code: image_url} map; codes that don't appear in the PDF text or have
    no images on their page are simply omitted."""
    if not codes or not image_records:
        return {}
    try:
        import fitz  # type: ignore
    except ImportError:
        return {}
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return {}

    by_page_images: dict[int, list[dict]] = {}
    for rec in image_records:
        if rec.get("y_top") is None:
            continue
        by_page_images.setdefault(rec["page_number"], []).append(rec)

    matches: dict[str, str] = {}
    try:
        for code in codes:
            if not code:
                continue
            code_str = str(code).strip()
            if not code_str:
                continue
            for page_idx in range(len(doc)):
                page = doc.load_page(page_idx)
                page_num = page_idx + 1
                hits = page.search_for(code_str)
                if not hits:
                    continue
                code_y = float(hits[0].y0)
                page_imgs = by_page_images.get(page_num, [])
                if not page_imgs:
                    continue
                best = min(
                    page_imgs,
                    key=lambda r: abs(((r["y_top"] + r["y_bottom"]) / 2) - code_y),
                )
                matches[code_str] = f"/api/uploads/{upload_id}_images/{best['filename']}"
                break
    finally:
        doc.close()
    return matches


def _ocr_to_preview(
    extracted: dict,
    upload_id: str,
    products: list[dict],
    image_lookup: Optional[dict[str, str]] = None,
    page_images: Optional[list[dict]] = None,
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

        image_url = None
        image_match_confidence = None
        if code and image_lookup:
            url = image_lookup.get(str(code).strip())
            if url:
                image_url = url
                image_match_confidence = "matched"

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
            "image_url": image_url,
            "image_match_confidence": image_match_confidence,
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
        "page_images": page_images or [],
        "summary": {
            "total_lines": len(items_out),
            "new_skus": sum(1 for i in items_out if i["proposed_sku"] and not i["already_exists"] and not i["skip_reason"]),
            "already_exists": sum(1 for i in items_out if i["already_exists"]),
            "skipped": sum(1 for i in items_out if i["skip_reason"]),
            "images_extracted": len(page_images or []),
            "items_with_image": sum(1 for i in items_out if i.get("image_url")),
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

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    upload_id = f"{stamp}-{_safe_filename(file.filename or 'upload')}"
    saved_path = UPLOAD_DIR / upload_id
    contents = await file.read()
    saved_path.write_bytes(contents)

    try:
        from supplier_ocr_pipeline import extract_with_deepseek_local
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"OCR pipeline import failed: {exc}",
        )

    try:
        extracted = extract_with_deepseek_local(
            document_name=file.filename or upload_id,
            file_path=saved_path,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OCR failed: {exc}")

    # Persist raw OCR alongside the upload so we can re-preview without re-OCR.
    raw_path = saved_path.with_suffix(saved_path.suffix + ".ocr.json")
    raw_path.write_text(json.dumps(extracted, indent=2, ensure_ascii=False), encoding="utf-8")

    # Pull embedded images out of the PDF and try to pair each one with an
    # OCR'd line item by Y-position. Soft-fail: a non-PDF or PyMuPDF-less
    # environment just yields zero images and the modal falls back to "no
    # image" cells, which is the pre-image-extraction behaviour.
    image_info: dict[str, Any] = {"page_images": [], "image_records": []}
    if (file.filename or "").lower().endswith(".pdf"):
        image_info = _extract_pdf_images(saved_path, upload_id)

    codes = [
        str(it.get("supplier_item_code")).strip()
        for it in extracted.get("items", [])
        if it.get("supplier_item_code")
    ]
    image_lookup = (
        _match_codes_to_images(saved_path, upload_id, codes, image_info["image_records"])
        if image_info["image_records"]
        else {}
    )

    data = _read_master()
    preview = _ocr_to_preview(
        extracted,
        upload_id=upload_id,
        products=data.get("products", []),
        image_lookup=image_lookup,
        page_images=image_info["page_images"],
    )
    return preview


@app.get("/api/uploads/{subdir}/{filename}")
def serve_upload(subdir: str, filename: str) -> FileResponse:
    """Serve an extracted image (or any other artefact) under data/uploads/.
    Confines the lookup to UPLOAD_DIR so callers can't escape with `../`."""
    target = (UPLOAD_DIR / subdir / filename).resolve()
    if not str(target).startswith(str(UPLOAD_DIR.resolve())) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(target))


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


# ── Manual SKU (no supplier order, no invoice) ───────────────────────────────
#
# For one-off items that don't go through the OCR ingest path. The Guardian
# artwork piece for Jewel Changi is the May-1 example: commissioned, no
# supplier code, no PO. Allocates a fresh SKU+PLU and writes an entry shaped
# like the OCR commit so it shows up in the same purchased_only filter.


class ManualProductRequest(BaseModel):
    description: str = Field(..., min_length=1)
    long_description: Optional[str] = None
    product_type: str = Field(..., min_length=1, description="e.g. 'Artwork', 'Bookend', 'Sphere'")
    material: str = Field(..., min_length=1, description="e.g. 'Mixed media', 'Crystal'")
    size: Optional[str] = None
    qty_on_hand: float = Field(default=1, ge=0)
    cost_price: Optional[float] = Field(default=None, ge=0, description="SGD; optional for commissioned/internal items")
    retail_price: Optional[float] = Field(default=None, gt=0, description="SGD; can be filled in later via /api/products/{sku} PATCH")
    supplier_id: str = Field(default="INTERNAL")
    supplier_name: str = Field(default="Internal / Manual")
    internal_code: Optional[str] = Field(default=None, description="Optional supplier-side code; auto-generated if absent")
    notes: Optional[str] = None


@app.post("/api/products/manual")
def create_manual_product(req: ManualProductRequest) -> dict:
    """Create a one-off SKU outside the OCR pipeline (e.g. Guardian artwork)."""
    from identifier_utils import allocate_identifier_pair, max_sku_sequence
    from add_hengwei_skus_to_master import (
        STOCKING_LOCATION,
        detect_material,
        detect_product_type,
        synth_description,
        synth_long_description,
    )

    with _lock:
        data = _read_master()
        products = data.setdefault("products", [])
        sku_set = {str(p["sku_code"]).strip() for p in products if p.get("sku_code")}
        plu_set: set[str] = set()
        for p in products:
            for f in ("nec_plu", "plu_code"):
                v = p.get(f)
                if v:
                    plu_set.add(str(v).strip())
        existing_codes = {
            str(p["internal_code"]).strip() for p in products if p.get("internal_code")
        }

        # Material/type abbreviations come from the same helpers the Hengwei
        # importer uses, so the SKU naming stays consistent.
        ocr_type_text = req.product_type.strip().lower()
        type_hit = _OCR_TYPE_TO_ABBR.get(ocr_type_text)
        if type_hit:
            type_abbr, type_label = type_hit
        else:
            type_abbr, _ts, type_label = detect_product_type(
                req.size or "", req.material, req.description
            )
        mat_abbr, mat_label = detect_material(req.material)

        # Auto-generate an internal_code if the caller didn't pass one.
        internal_code = (req.internal_code or "").strip()
        if not internal_code:
            base = f"MANUAL-{type_abbr}-"
            n = 1
            while f"{base}{n:03d}" in existing_codes:
                n += 1
            internal_code = f"{base}{n:03d}"
        elif internal_code in existing_codes:
            raise HTTPException(
                status_code=409,
                detail=f"internal_code '{internal_code}' already in master_product_list.json",
            )

        next_seq = max(max_sku_sequence(sku_set), 0) + 1

        def _sku_factory(seq: int, _ta=type_abbr, _ma=mat_abbr) -> str:
            return f"VE{_ta}{_ma}{seq:07d}"

        sku_code, plu_code, _ = allocate_identifier_pair(
            _sku_factory, sku_set, plu_set, next_seq
        )

        description = req.description or synth_description(
            type_label, mat_label, req.size or "", internal_code
        )
        long_description = req.long_description or synth_long_description(
            type_label, mat_label, req.size or "", req.material
        )

        entry = {
            "id": f"{req.supplier_id.lower()}-{internal_code.lower()}",
            "internal_code": internal_code,
            "sku_code": sku_code,
            "description": description,
            "long_description": long_description,
            "material": mat_label,
            "product_type": type_label,
            "category": "Home Decor",
            "amazon_sku": f"VE-{mat_abbr}-{sku_code[2:5]}-{internal_code}",
            "google_product_id": f"online:en:SG:{sku_code}",
            "google_product_category": "Home & Garden > Decor",
            "nec_plu": plu_code,
            "cost_price": req.cost_price,
            "cost_currency": "SGD" if req.cost_price is not None else None,
            "cost_basis": None,
            "retail_price": req.retail_price,
            "qty_on_hand": req.qty_on_hand,
            "supplier_id": req.supplier_id,
            "supplier_name": req.supplier_name,
            "supplier_item_code": internal_code,
            # Tagged like an invoice-sourced SKU so the purchased_only filter
            # picks it up — `manual_<timestamp>` keeps it traceable.
            "source_orders": [f"manual_{datetime.now().strftime('%Y%m%d-%H%M%S')}"],
            "sources": [f"{req.supplier_id.lower()}_invoice_manual_{datetime.now().strftime('%Y%m%d-%H%M%S')}"],
            "raw_names": [description],
            "mention_count": 1,
            "inventory_type": "purchased",
            "sourcing_strategy": "internal_manual",
            "inventory_category": "finished_for_sale",
            "sale_ready": bool(req.retail_price),
            "block_sales": False,
            "stocking_status": "in_stock",
            "stocking_location": STOCKING_LOCATION,
            "use_stock": True,
            "size": req.size or "",
            "added_at": _now(),
            "added_via": "master_data_api/create_manual_product",
            "needs_review": False,
            "needs_retail_price": req.retail_price is None,
            "notes": req.notes,
        }
        products.append(entry)
        meta = data.setdefault("metadata", {})
        meta["last_modified"] = _now()
        meta["last_modified_by"] = "master_data_api/create_manual_product"
        _atomic_write_master(data)
        return entry


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


# ── Visual search by photo (Gemini vision → embed → cosine vs catalog) ──────
#
# Reuses the existing `data/catalog/product_embeddings.npy` (built by
# tools/pipelines/product_image_pipeline.py with gemini-embedding-2-preview).
# When the user uploads a photo of an item — e.g. snapped on the showroom
# floor — we run the same VISION_PROMPT against gemini-2.5-flash, embed the
# description with the same model, and cosine-match against the catalog
# index. Each match is cross-referenced to master_product_list.json by
# internal_code (with a base-code fallback so e.g. A339A also matches A339).

_VISUAL_SEARCH_PROMPT = """You are a luxury retail product cataloguing AI.
Analyse this product image and return ONLY a JSON object with these exact fields:

{
  "dominant_colour": "<primary colour of the object, e.g. gold, amber, green>",
  "secondary_colour": "<secondary colour if present, else null>",
  "material_type": "<main material, e.g. copper, crystal, marble, glass, stone>",
  "secondary_material": "<secondary material if present, else null>",
  "object_shape": "<shape/form, e.g. bookend, vase, figurine, candleholder, bowl, tower>",
  "style_tags": ["<tag1>", "<tag2>", "<tag3>"],
  "estimated_height_cm": <number or null>,
  "surface_finish": "<e.g. polished, matte, textured, rough>",
  "visual_description": "<2-3 sentence vivid English description of the product for a luxury catalogue>"
}

Be precise. Do not add commentary outside the JSON object."""


def _visual_index_text(d: dict) -> str:
    """Re-create the same flat description string used when the catalog index
    was originally built, so embedding-space distances remain comparable."""
    shape = d.get("object_shape") or "object"
    material = d.get("material_type") or "unknown material"
    secondary_material = d.get("secondary_material")
    if secondary_material:
        material = f"{material} and {secondary_material}"
    colour = d.get("dominant_colour") or "unspecified"
    secondary_colour = d.get("secondary_colour")
    if secondary_colour:
        colour = f"{colour} and {secondary_colour}"
    style = ", ".join(d.get("style_tags") or []) or "classic"
    description = d.get("visual_description") or ""
    return (
        f"{shape} made of {material}. Colour: {colour}. Style: {style}. "
        f"{description}"
    ).strip()


def _build_internal_code_index(products: list[dict]) -> dict[str, dict]:
    """Map both the full internal_code (A339A) and its base form (A339) to a
    representative product entry. Lets us surface SKUs even when only a
    base-code variant is in the catalog."""
    by_code: dict[str, dict] = {}
    for p in products:
        code = (p.get("internal_code") or "").strip()
        if not code:
            continue
        by_code.setdefault(code, p)
        base = re.match(r"^([A-Za-z]+\d+)", code)
        if base:
            by_code.setdefault(base.group(1), p)
    return by_code


@app.post("/api/ai/visual_search")
async def visual_search(
    file: UploadFile = File(...),
    top_k: int = Query(8, ge=1, le=30),
) -> dict:
    """Find the closest catalog items to an uploaded photo.

    Returns a list of `{code, file, image_url, similarity, sku, ...}` ordered
    by descending cosine similarity. Useful when a customer/staff member
    points at an item they want to look up but doesn't know the SKU."""
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="GEMINI_API_KEY not set on the server (required for visual search — same key used by tools/pipelines/product_image_pipeline.py).",
        )
    if not CATALOG_EMBED_NPY.exists() or not CATALOG_EMBED_INDEX.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Catalog visual index missing. Run "
                "`python tools/pipelines/product_image_pipeline.py` first to "
                "build data/catalog/product_embeddings.npy + product_embedding_index.json."
            ),
        )

    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"numpy not available: {exc}")
    try:
        from google import genai  # type: ignore
        from google.genai import types as genai_types  # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"google-genai not installed: {exc}. Add it with `pip install google-genai`.",
        )

    img_bytes = await file.read()
    if not img_bytes:
        raise HTTPException(status_code=400, detail="empty image upload")

    mime = file.content_type or "image/png"
    if mime == "application/octet-stream":
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:
        vision_resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                genai_types.Part.from_bytes(data=img_bytes, mime_type=mime),
                _VISUAL_SEARCH_PROMPT,
            ],
            config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini vision call failed: {exc}")

    raw_text = (vision_resp.text or "").strip()
    raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text, flags=re.MULTILINE).strip("` \n")
    try:
        descriptor = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini returned non-JSON: {exc}; raw={raw_text[:200]}")

    query_text = _visual_index_text(descriptor)

    try:
        embed_resp = client.models.embed_content(
            model="gemini-embedding-2-preview",
            contents=query_text,
            config=genai_types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        query_vec = np.asarray(embed_resp.embeddings[0].values, dtype="float32")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini embedding call failed: {exc}")

    catalog_emb = np.load(str(CATALOG_EMBED_NPY))
    catalog_idx = json.loads(CATALOG_EMBED_INDEX.read_text(encoding="utf-8"))

    if query_vec.shape[-1] != catalog_emb.shape[-1]:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Embedding dimension mismatch (query={query_vec.shape[-1]}, "
                f"catalog={catalog_emb.shape[-1]}) — rebuild the catalog index "
                f"with the current EMBED_MODEL."
            ),
        )

    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    cat_norms = catalog_emb / (np.linalg.norm(catalog_emb, axis=1, keepdims=True) + 1e-9)
    sims = cat_norms @ q_norm
    order = np.argsort(-sims)[:top_k]

    by_code = _build_internal_code_index(_read_master().get("products", []))
    matches: list[dict] = []
    for rank, i in enumerate(order):
        entry = catalog_idx[int(i)]
        code = entry.get("code")
        product = by_code.get(code) if code else None
        # Fallback: trim a trailing colour/letter suffix, e.g. "A340粉" → "A340"
        if not product and code:
            base = re.match(r"^([A-Za-z]+\d+)", code)
            if base:
                product = by_code.get(base.group(1))
        matches.append({
            "rank": rank + 1,
            "code": code,
            "file": entry.get("file"),
            "image_url": f"/api/catalog/images/{entry.get('file')}" if entry.get("file") else None,
            "similarity": float(sims[int(i)]),
            "catalog_text": entry.get("text"),
            "sku": product.get("sku_code") if product else None,
            "nec_plu": product.get("nec_plu") if product else None,
            "description": product.get("description") if product else None,
            "retail_price": product.get("retail_price") if product else None,
            "qty_on_hand": product.get("qty_on_hand") if product else None,
        })

    return {
        "descriptor": descriptor,
        "query_text": query_text,
        "matches": matches,
        "catalog_size": int(catalog_emb.shape[0]),
    }


@app.get("/api/catalog/images/{filename}")
def serve_catalog_image(filename: str) -> FileResponse:
    """Serve a product catalog PNG. Confined to CATALOG_IMAGES_DIR so the
    URL path can't traverse outside it."""
    target = (CATALOG_IMAGES_DIR / filename).resolve()
    if not str(target).startswith(str(CATALOG_IMAGES_DIR.resolve())) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(target))


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
