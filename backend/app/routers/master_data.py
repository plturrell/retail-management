"""Auth-protected master-data endpoints used by web and native clients."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse

from app.auth.dependencies import RoleEnum, require_any_store_role

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.server import master_data_api as legacy_master_data

router = APIRouter(prefix="/api/master-data", tags=["master-data"])


@router.get("/health")
def health(
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return legacy_master_data.health()


@router.get("/stats")
def stats(
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return legacy_master_data.stats()


@router.get("/products")
def list_products(
    launch_only: bool = Query(True),
    needs_price: bool = Query(False),
    supplier: Optional[str] = Query(None),
    purchased_only: bool = Query(True),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return legacy_master_data.list_products(
        launch_only=launch_only,
        needs_price=needs_price,
        supplier=supplier,
        purchased_only=purchased_only,
    )


@router.get("/products/{sku}")
def get_product(
    sku: str,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return legacy_master_data.get_product(sku)


@router.patch("/products/{sku}")
def patch_product(
    sku: str,
    patch: legacy_master_data.ProductPatch,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return legacy_master_data.patch_product(sku, patch)


@router.post("/export/nec_jewel")
def export_nec_jewel(
    store: str = "JEWEL-01",
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    result = legacy_master_data.export_nec_jewel(store=store)
    if result.get("download_url"):
        result["download_url"] = result["download_url"].replace("/api/exports/", "/api/master-data/exports/")
    return result


@router.get("/exports/{filename}")
def download_export(
    filename: str,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> FileResponse:
    return legacy_master_data.download_export(filename)


@router.post("/ingest/invoice")
async def ingest_invoice(
    file: UploadFile = File(...),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return await legacy_master_data.ingest_invoice(file)


@router.post("/ingest/invoice/commit")
def commit_invoice(
    req: legacy_master_data.IngestCommitRequest,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return legacy_master_data.commit_invoice(req)


@router.post("/ai/recommend_prices")
def recommend_prices(
    req: legacy_master_data.RecommendPricesRequest,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
) -> dict:
    return legacy_master_data.recommend_prices(req)
