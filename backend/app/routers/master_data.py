"""Auth-protected master-data endpoints used by web and native clients."""

from __future__ import annotations

import sys
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import RoleEnum, require_any_store_role
from app.firestore_helpers import (
    create_document,
    get_document,
    query_collection,
    update_document,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from tools.server import master_data_api as legacy_master_data
except ModuleNotFoundError:
    legacy_master_data = None


class _UnavailableLegacyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


ProductPatch = legacy_master_data.ProductPatch if legacy_master_data else _UnavailableLegacyRequest
ExportLabelsRequest = legacy_master_data.ExportLabelsRequest if legacy_master_data else _UnavailableLegacyRequest
IngestCommitRequest = legacy_master_data.IngestCommitRequest if legacy_master_data else _UnavailableLegacyRequest
RecommendPricesRequest = legacy_master_data.RecommendPricesRequest if legacy_master_data else _UnavailableLegacyRequest


def _legacy_master_data():
    if legacy_master_data is None:
        raise HTTPException(
            status_code=503,
            detail="Legacy master-data tooling is not packaged in this backend image.",
        )
    return legacy_master_data

router = APIRouter(prefix="/api/master-data", tags=["master-data"])


@router.get("/health")
def health(
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.health()


@router.get("/stats")
def stats(
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.stats()


@router.get("/products")
def list_products(
    launch_only: bool = Query(True),
    needs_price: bool = Query(False),
    supplier: Optional[str] = Query(None),
    purchased_only: bool = Query(True),
    sourcing_strategy: Optional[str] = Query(None),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.list_products(
        launch_only=launch_only,
        needs_price=needs_price,
        supplier=supplier,
        purchased_only=purchased_only,
        sourcing_strategy=sourcing_strategy,
    )


@router.get("/products/{sku}")
def get_product(
    sku: str,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.get_product(sku)


@router.patch("/products/{sku}")
def patch_product(
    sku: str,
    patch: ProductPatch,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.patch_product(sku, patch)


@router.post("/export/nec_jewel")
def export_nec_jewel(
    store: str = "JEWEL-01",
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    result = legacy_master_data.export_nec_jewel(store=store)
    if result.get("download_url"):
        result["download_url"] = result["download_url"].replace("/api/exports/", "/api/master-data/exports/")
    return result


@router.post("/export/labels")
def export_labels(
    req: ExportLabelsRequest,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    result = legacy_master_data.export_labels(req)
    if result.get("download_url"):
        result["download_url"] = result["download_url"].replace("/api/exports/", "/api/master-data/exports/")
    return result


@router.get("/exports/{filename}")
def download_export(
    filename: str,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> FileResponse:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.download_export(filename)


@router.get("/pos-status")
def pos_status(
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    """Return which PLUs are currently published in Firestore and which of
    those have a currently-valid price doc. Used by the master-data UI to
    render the 'Live in POS' column."""
    today = date.today().isoformat()
    plus_docs = query_collection("plus")
    price_docs = query_collection("prices")
    priced_sku_ids = {
        p.get("sku_id") for p in price_docs
        if p.get("sku_id")
        and (p.get("valid_from") or "0000-01-01") <= today
        and (p.get("valid_to") or "9999-12-31") >= today
    }
    plus_status: dict[str, dict] = {}
    for plu in plus_docs:
        code = plu.get("plu_code")
        if not code:
            continue
        plus_status[str(code)] = {
            "in_plus": True,
            "has_current_price": plu.get("sku_id") in priced_sku_ids,
        }
    return {"as_of": today, "plus": plus_status}


@router.post("/ingest/invoice")
async def ingest_invoice(
    file: UploadFile = File(...),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return await legacy_master_data.ingest_invoice(file)


@router.post("/ingest/invoice/commit")
def commit_invoice(
    req: IngestCommitRequest,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.commit_invoice(req)


@router.post("/ai/recommend_prices")
def recommend_prices(
    req: RecommendPricesRequest,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    legacy_master_data = _legacy_master_data()
    return legacy_master_data.recommend_prices(req)


class PublishPriceRequest(BaseModel):
    retail_price: float = Field(gt=0, description="Tax-inclusive retail price (SGD).")
    store_code: str = Field(default="JEWEL-01")


@router.post("/products/{sku}/publish_price")
def publish_price(
    sku: str,
    req: PublishPriceRequest,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    """Publish *sku*'s retail price to Firestore so the POS barcode lookup
    returns it. Idempotent end-to-end:

      1. Persists retail_price + retail_price_set_at in master JSON (via the
         existing legacy patch_product).
      2. Ensures Firestore plus/{id} and skus/{id} docs exist for this SKU,
         creating or updating them as needed.
      3. Supersedes any currently-active prices/{id} doc for the SKU by
         setting valid_to = yesterday.
      4. Creates a new prices/{id} doc with valid_from = today and
         valid_to = +5 years.
    """
    legacy = _legacy_master_data()

    patch = legacy.ProductPatch(retail_price=req.retail_price)
    product = legacy.patch_product(sku, patch)

    plu_code = (product.get("nec_plu") or "").strip()
    if not plu_code:
        raise HTTPException(
            status_code=400,
            detail=f"sku {sku} has no nec_plu; cannot publish to POS",
        )

    store_matches = query_collection(
        "stores", filters=[("store_code", "==", req.store_code)], limit=1
    )
    if not store_matches:
        raise HTTPException(
            status_code=400,
            detail=f"store_code {req.store_code} not found in Firestore stores collection",
        )
    store_id = str(store_matches[0]["id"])

    plus_matches = query_collection(
        "plus", filters=[("plu_code", "==", plu_code)], limit=1
    )
    if plus_matches:
        plu_doc = plus_matches[0]
        sku_id = str(plu_doc.get("sku_id") or "")
        plu_id = str(plu_doc["id"])
    else:
        sku_matches = query_collection(
            "skus", filters=[("sku_code", "==", sku)], limit=1
        )
        sku_id = str(sku_matches[0]["id"]) if sku_matches else str(_uuid.uuid4())
        plu_id = str(_uuid.uuid4())

    now = datetime.now(timezone.utc)
    sku_doc_data = {
        "id": sku_id,
        "sku_code": sku[:32],
        "description": (product.get("description") or "")[:60],
        "long_description": product.get("long_description"),
        "cost_price": float(product["cost_price"]) if product.get("cost_price") is not None else None,
        "store_id": store_id,
        "brand_id": None,
        "category_id": None,
        "tax_code": "G",
        "is_unique_piece": False,
        "use_stock": bool(product.get("use_stock", True)),
        "block_sales": bool(product.get("block_sales", False)),
        "internal_code": product.get("internal_code"),
        "nec_plu": plu_code,
        "material": product.get("material"),
        "product_type": product.get("product_type"),
        "source": "master_data_publish_price",
        "updated_at": now,
    }
    existing_sku = get_document("skus", sku_id) if sku_id else None
    if existing_sku:
        update_document("skus", sku_id, sku_doc_data)
    else:
        sku_doc_data["created_at"] = now
        create_document("skus", sku_doc_data, doc_id=sku_id)

    if plus_matches:
        update_document("plus", plu_id, {"plu_code": plu_code, "sku_id": sku_id})
    else:
        create_document(
            "plus",
            {"id": plu_id, "plu_code": plu_code, "sku_id": sku_id},
            doc_id=plu_id,
        )

    today = date.today()
    today_iso = today.isoformat()
    yesterday_iso = (today - timedelta(days=1)).isoformat()
    superseded: list[str] = []
    for old in query_collection("prices", filters=[("sku_id", "==", sku_id)]):
        old_id = old.get("id")
        if not old_id:
            continue
        vf = old.get("valid_from") or "0000-01-01"
        vt = old.get("valid_to") or "9999-12-31"
        if vf <= today_iso <= vt:
            update_document(
                "prices",
                str(old_id),
                {"valid_to": yesterday_iso, "updated_at": now},
            )
            superseded.append(str(old_id))

    price_id = str(_uuid.uuid4())
    price_doc = {
        "id": price_id,
        "sku_id": sku_id,
        "store_id": store_id,
        "price_incl_tax": float(req.retail_price),
        "price_excl_tax": round(float(req.retail_price) / 1.09, 2),
        "price_unit": 1,
        "valid_from": today_iso,
        "valid_to": date(today.year + 5, 12, 31).isoformat(),
        "source": "master_data_publish",
        "created_at": now,
        "updated_at": now,
    }
    create_document("prices", price_doc, doc_id=price_id)

    return {
        "ok": True,
        "sku": sku,
        "plu_code": plu_code,
        "sku_id": sku_id,
        "plu_id": plu_id,
        "price_id": price_id,
        "retail_price": float(req.retail_price),
        "valid_from": price_doc["valid_from"],
        "valid_to": price_doc["valid_to"],
        "superseded_price_ids": superseded,
        "store_id": store_id,
        "product": product,
    }
