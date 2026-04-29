"""Auth-protected master-data endpoints used by web and native clients."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from app.auth.dependencies import RoleEnum, require_any_store_role
from app.firestore_helpers import query_collection

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
