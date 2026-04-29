"""Auth-protected master-data endpoints used by web and native clients."""

from __future__ import annotations

import sys
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.audit import log_event
from app.auth.dependencies import (
    RoleEnum,
    ensure_any_store_role,
    get_current_user,
    require_any_store_role,
)
from app.config import settings
from app.firestore_helpers import (
    create_document,
    get_document,
    query_collection,
    update_document,
)
from app.services.tax import price_excl_from_inclusive


def _publisher_emails() -> frozenset[str]:
    """Lowercased allowlist of emails permitted to publish prices to POS."""
    return frozenset(e.strip().lower() for e in settings.MASTER_DATA_PUBLISHER_EMAILS if e and e.strip())


def _assert_publish_allowed(actor: dict) -> None:
    """Raise 403 if *actor* is not on the publisher allowlist.

    Used to gate any path that writes a price into the live Firestore
    ``prices`` collection. The role-at-any-store owner check is enforced
    separately by the FastAPI dependency.
    """
    raw_email = actor.get("email") if isinstance(actor, dict) else getattr(actor, "email", None)
    email = (raw_email or "").strip().lower()
    if email not in _publisher_emails():
        raise HTTPException(
            status_code=403,
            detail="Publishing prices to POS is restricted to the named owner accounts.",
        )


async def require_publish_price_owner(
    actor: dict = Depends(get_current_user),
) -> dict:
    """Combined gate for the master-data publish endpoints: caller must hold
    ``owner`` role at any store **and** be on the publisher email allowlist.
    Returns the user dict so endpoints can use it as the audit ``actor``.
    """
    ensure_any_store_role(actor, RoleEnum.owner)
    _assert_publish_allowed(actor)
    return actor

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
ManualProductCreateRequest = (
    legacy_master_data.ManualProductCreateRequest if legacy_master_data else _UnavailableLegacyRequest
)


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
    active_by_sku: dict[str, str] = {}
    for p in price_docs:
        sku_id = p.get("sku_id")
        pid = p.get("id")
        if not sku_id or not pid:
            continue
        if (p.get("valid_from") or "0000-01-01") <= today <= (p.get("valid_to") or "9999-12-31"):
            # If multiple are somehow active (shouldn't happen post-supersede),
            # the last one wins — caller will refresh either way.
            active_by_sku[str(sku_id)] = str(pid)

    plus_status: dict[str, dict] = {}
    for plu in plus_docs:
        code = plu.get("plu_code")
        if not code:
            continue
        sku_id = plu.get("sku_id")
        active_price_id = active_by_sku.get(str(sku_id)) if sku_id else None
        plus_status[str(code)] = {
            "in_plus": True,
            "has_current_price": active_price_id is not None,
            "active_price_id": active_price_id,
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
    retail_price: float = Field(gt=0, description="Tax-inclusive retail price.")
    store_code: str = Field(default="JEWEL-01")
    currency: str = Field(default="SGD", min_length=3, max_length=3, description="ISO 4217 currency code.")
    tax_code: str = Field(default="G", description="Tax code for excl-tax derivation. G=GST 9%, E=exempt, Z=zero-rated.")
    expected_active_price_id: Optional[str] = Field(
        default=None,
        description=(
            "Concurrency guard: if set, server requires this be the currently-active "
            "price doc id for the SKU (or an empty string if the SKU has none). "
            "Returns 409 if a different price has been published since the client "
            "loaded the row."
        ),
    )


def _resolve_publish_context(
    sku: str,
    req: PublishPriceRequest,
) -> tuple[dict[str, Any], str, str, str, list[dict[str, Any]]]:
    """Shared lookups for publish_price: returns (product, plu_code, store_id,
    sku_id_or_empty, current_active_prices). Raises HTTPException on validation
    failures so the route handler stays linear."""
    legacy = _legacy_master_data()
    product = legacy.get_product(sku)

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

    sku_matches = query_collection("skus", filters=[("sku_code", "==", sku)], limit=1)
    sku_id = str(sku_matches[0]["id"]) if sku_matches else ""

    today_iso = date.today().isoformat()
    active_prices: list[dict[str, Any]] = []
    if sku_id:
        for p in query_collection("prices", filters=[("sku_id", "==", sku_id)]):
            vf = p.get("valid_from") or "0000-01-01"
            vt = p.get("valid_to") or "9999-12-31"
            if vf <= today_iso <= vt:
                active_prices.append(p)

    return product, plu_code, store_id, sku_id, active_prices


def _do_publish_price(
    sku: str,
    req: PublishPriceRequest,
    *,
    actor: Any,
    request: Optional[Request],
) -> dict:
    """Core price-publish logic, callable directly from other route handlers
    (e.g. the manual create+publish flow) without re-running the FastAPI
    dependency stack. Side-effects identical to the public route.

    Defense-in-depth: re-asserts the publisher allowlist gate so any inline
    caller (e.g. ``create_product_route``) can't accidentally bypass it by
    forgetting to call ``require_publish_price_owner`` at their own boundary.
    """
    _assert_publish_allowed(actor)
    legacy = _legacy_master_data()

    # Resolve current Firestore state *before* mutating master JSON so a 409
    # conflict doesn't leave a half-applied retail_price update behind.
    _product_pre, plu_code, store_id, sku_id_pre, active_prices = _resolve_publish_context(sku, req)

    if req.expected_active_price_id is not None:
        current_id = str(active_prices[0]["id"]) if active_prices else ""
        if current_id != req.expected_active_price_id.strip():
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "price_changed",
                    "message": "Another price has been published since you loaded this row. Refresh and try again.",
                    "expected": req.expected_active_price_id,
                    "actual": current_id or None,
                },
            )

    patch = legacy.ProductPatch(retail_price=req.retail_price)
    product = legacy.patch_product(sku, patch)

    plus_matches = query_collection(
        "plus", filters=[("plu_code", "==", plu_code)], limit=1
    )
    if plus_matches:
        plu_doc = plus_matches[0]
        sku_id = str(plu_doc.get("sku_id") or "")
        plu_id = str(plu_doc["id"])
    else:
        sku_id = sku_id_pre or str(_uuid.uuid4())
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
        "tax_code": req.tax_code.upper(),
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
    # Re-query so we catch any active price that was created between the
    # context resolve and this point (rare, but cheap insurance).
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

    tax_code = req.tax_code.upper()
    excl_tax = float(price_excl_from_inclusive(Decimal(str(req.retail_price)), tax_code))
    actor_email = actor.get("email") if isinstance(actor, dict) else getattr(actor, "email", None)
    actor_uid = (
        actor.get("firebase_uid") if isinstance(actor, dict) else getattr(actor, "firebase_uid", None)
    )
    actor_user_id = actor.get("id") if isinstance(actor, dict) else getattr(actor, "id", None)

    price_id = str(_uuid.uuid4())
    price_doc = {
        "id": price_id,
        "sku_id": sku_id,
        "store_id": store_id,
        "price_incl_tax": float(req.retail_price),
        "price_excl_tax": excl_tax,
        "price_unit": 1,
        "currency": req.currency.upper(),
        "tax_code": tax_code,
        "valid_from": today_iso,
        "valid_to": date(today.year + 5, 12, 31).isoformat(),
        "source": "master_data_publish",
        "created_at": now,
        "updated_at": now,
        "created_by_uid": actor_uid,
        "created_by_email": actor_email,
        "superseded_price_ids": superseded,
    }
    create_document("prices", price_doc, doc_id=price_id)

    log_event(
        "master_data.price_publish",
        actor=actor,
        metadata={
            "sku_code": sku,
            "plu_code": plu_code,
            "sku_id": sku_id,
            "store_code": req.store_code,
            "store_id": store_id,
            "price_id": price_id,
            "retail_price": float(req.retail_price),
            "currency": req.currency.upper(),
            "tax_code": tax_code,
            "superseded_price_ids": superseded,
        },
        request=request,
    )

    return {
        "ok": True,
        "sku": sku,
        "plu_code": plu_code,
        "sku_id": sku_id,
        "plu_id": plu_id,
        "price_id": price_id,
        "retail_price": float(req.retail_price),
        "currency": req.currency.upper(),
        "tax_code": tax_code,
        "valid_from": price_doc["valid_from"],
        "valid_to": price_doc["valid_to"],
        "superseded_price_ids": superseded,
        "store_id": store_id,
        "product": product,
        "audit": {
            "actor_email": actor_email,
            "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
        },
    }


@router.post("/products/{sku}/publish_price")
def publish_price(
    sku: str,
    req: PublishPriceRequest,
    request: Request,
    actor: dict = Depends(require_publish_price_owner),
) -> dict:
    """Publish *sku*'s retail price to Firestore so the POS barcode lookup
    returns it. See ``_do_publish_price`` for the body.

    Restricted to the publisher email allowlist
    (``settings.MASTER_DATA_PUBLISHER_EMAILS``) on top of the owner role check.

    Concurrency: pass req.expected_active_price_id from the client (or "" if
    none was active when the row was loaded) to opt into optimistic locking;
    publishes that conflict with a newer active price are rejected with 409.
    """
    return _do_publish_price(sku, req, actor=actor, request=request)


class ManualCreateAndPublishRequest(BaseModel):
    """Wrapper around the legacy ManualProductCreateRequest plus optional
    inline price-publish, so the staff portal can do create+price in one click."""

    model_config = ConfigDict(extra="allow")

    description: str = Field(min_length=1, max_length=120)
    long_description: Optional[str] = None
    product_type: str = Field(min_length=1)
    material: str = Field(min_length=1)
    size: Optional[str] = None
    supplier_id: str = Field(default="CN-001")
    supplier_name: Optional[str] = None
    internal_code: Optional[str] = None
    cost_price: Optional[float] = Field(default=None, ge=0)
    cost_currency: Optional[str] = Field(default="SGD")
    qty_on_hand: Optional[int] = Field(default=None, ge=0)
    sku_code: Optional[str] = None
    nec_plu: Optional[str] = None
    sourcing_strategy: str = Field(default="supplier_premade")
    inventory_type: str = Field(default="purchased")
    notes: Optional[str] = None

    # Optional inline publish — when retail_price is set, the server creates
    # the SKU then immediately publishes the price in the same request so the
    # staff portal can do create+price in one click.
    retail_price: Optional[float] = Field(default=None, gt=0)
    store_code: str = Field(default="JEWEL-01")
    currency: str = Field(default="SGD", min_length=3, max_length=3)
    tax_code: str = Field(default="G")


@router.post("/products")
def create_product_route(
    req: ManualCreateAndPublishRequest,
    request: Request,
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
    actor: dict = Depends(get_current_user),
) -> dict:
    """Append a hand-entered SKU to the master JSON (no invoice required) and,
    if ``retail_price`` is provided, immediately publish that price to
    Firestore so the new SKU is live in POS in a single round-trip.

    SKU creation only requires the owner role (any store). The optional inline
    price publish additionally requires the publisher email allowlist; the
    check runs *before* the master-JSON write so we never leave a SKU behind
    that the caller wasn't allowed to price.
    """
    if req.retail_price is not None:
        # Surface the publisher-allowlist 403 up front rather than after the
        # SKU has been appended to master_product_list.json.
        _assert_publish_allowed(actor)

    legacy = _legacy_master_data()

    actor_email = actor.get("email") if isinstance(actor, dict) else getattr(actor, "email", None)
    legacy_req = legacy.ManualProductCreateRequest(
        description=req.description,
        long_description=req.long_description,
        product_type=req.product_type,
        material=req.material,
        size=req.size,
        supplier_id=req.supplier_id,
        supplier_name=req.supplier_name,
        internal_code=req.internal_code,
        cost_price=req.cost_price,
        cost_currency=req.cost_currency,
        qty_on_hand=req.qty_on_hand,
        sku_code=req.sku_code,
        nec_plu=req.nec_plu,
        sourcing_strategy=req.sourcing_strategy,
        inventory_type=req.inventory_type,
        notes=req.notes,
    )
    product = legacy.create_product(legacy_req, created_by=actor_email or "unknown")

    log_event(
        "master_data.product_create",
        actor=actor,
        metadata={
            "sku_code": product.get("sku_code"),
            "nec_plu": product.get("nec_plu"),
            "supplier_id": product.get("supplier_id"),
            "internal_code": product.get("internal_code"),
            "product_type": product.get("product_type"),
            "material": product.get("material"),
        },
        request=request,
    )

    publish_result: Optional[dict] = None
    if req.retail_price is not None:
        # Same allowlist as POST /products/{sku}/publish_price — only the
        # named publisher accounts may write a price into the live Firestore
        # prices collection, even via the create+publish convenience path.
        _assert_publish_allowed(actor)
        publish_req = PublishPriceRequest(
            retail_price=req.retail_price,
            store_code=req.store_code,
            currency=req.currency,
            tax_code=req.tax_code,
            expected_active_price_id="",  # brand-new SKU, no prior active price
        )
        publish_result = _do_publish_price(
            product["sku_code"], publish_req, actor=actor, request=request
        )
        product = publish_result.get("product", product)

    return {
        "ok": True,
        "product": product,
        "publish_result": publish_result,
    }
