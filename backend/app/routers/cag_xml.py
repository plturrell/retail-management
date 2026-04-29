from __future__ import annotations

import uuid as _uuid
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as SafeET
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import (
    batch_write,
    create_document,
    get_document,
    query_collection,
    update_document,
)
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse

router = APIRouter(prefix="/api", tags=["cag-xml"])


def _text(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/import/cag-xml", response_model=DataResponse[dict])
async def import_cag_xml(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Import CAG XML file and upsert categories, SKUs, PLUs, prices, promotions."""
    content = await file.read()
    try:
        root = SafeET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {e}")

    counts = {"categories": 0, "skus": 0, "plus": 0, "prices": 0, "promotions": 0}
    batch_ops = []

    # --- Categories ---
    for catg_el in root.findall(".//CATG"):
        parent_code = _text(catg_el, "parent_catg_code")
        child_code = _text(catg_el, "child_catg_code")
        catg_desc = _text(catg_el, "catg_desc") or ""
        cag_code = _text(catg_el, "cag_catg_code")
        store_id_str = _text(catg_el, "store_id")

        if not child_code or not store_id_str:
            continue

        existing = query_collection("categories", filters=[("catg_code", "==", child_code), ("store_id", "==", store_id_str)], limit=1)

        parent_id = None
        if parent_code:
            parents = query_collection("categories", filters=[("catg_code", "==", parent_code), ("store_id", "==", store_id_str)], limit=1)
            if parents:
                parent_id = parents[0].get("id")

        if existing:
            update_document("categories", existing[0]["id"], {"description": catg_desc, "cag_catg_code": cag_code, "parent_id": parent_id})
        else:
            doc_id = str(_uuid.uuid4())
            batch_ops.append({"action": "create", "collection": "categories", "doc_id": doc_id, "data": {
                "catg_code": child_code, "description": catg_desc, "cag_catg_code": cag_code,
                "store_id": store_id_str, "parent_id": parent_id,
            }})
        counts["categories"] += 1

    if batch_ops:
        batch_write(batch_ops)
        batch_ops = []

    # --- SKUs ---
    for sku_el in root.findall(".//SKU"):
        sku_code = _text(sku_el, "sku_code")
        if not sku_code:
            continue

        sku_desc = _text(sku_el, "sku_desc") or ""
        cost_str = _text(sku_el, "cost_price")
        cost_price = float(cost_str) if cost_str else None
        catg_code = _text(sku_el, "sku_catg_tenant")
        tax_code = _text(sku_el, "tax_code") or "G"
        brand_name = _text(sku_el, "brand")
        gender = _text(sku_el, "gender")
        age_group = _text(sku_el, "age_group")
        use_stock_str = _text(sku_el, "use_stock")
        block_sales_str = _text(sku_el, "block_sales")
        store_id_str = _text(sku_el, "store_id")

        if not store_id_str:
            continue

        use_stock = use_stock_str in ("Y", "1", "true", "True") if use_stock_str else True
        block_sales = block_sales_str in ("Y", "1", "true", "True") if block_sales_str else False

        category_id = None
        if catg_code:
            cats = query_collection("categories", filters=[("catg_code", "==", catg_code), ("store_id", "==", store_id_str)], limit=1)
            if cats:
                category_id = cats[0].get("id")

        brand_id = None
        if brand_name:
            brands = query_collection("brands", filters=[("name", "==", brand_name)], limit=1)
            if brands:
                brand_id = brands[0].get("id")
            else:
                brand_id = str(_uuid.uuid4())
                create_document("brands", {"name": brand_name}, doc_id=brand_id)

        existing = query_collection("skus", filters=[("sku_code", "==", sku_code)], limit=1)
        sku_data = {
            "description": sku_desc, "cost_price": cost_price, "category_id": category_id,
            "brand_id": brand_id, "tax_code": tax_code, "gender": gender, "age_group": age_group,
            "use_stock": use_stock, "block_sales": block_sales,
        }

        if existing:
            update_document("skus", existing[0]["id"], sku_data)
        else:
            sku_data["sku_code"] = sku_code
            sku_data["store_id"] = store_id_str
            batch_ops.append({"action": "create", "collection": "skus", "doc_id": str(_uuid.uuid4()), "data": sku_data})
        counts["skus"] += 1

    if batch_ops:
        batch_write(batch_ops)
        batch_ops = []

    # --- PLUs ---
    for plu_el in root.findall(".//PLU"):
        plu_code = _text(plu_el, "plu_code")
        sku_code = _text(plu_el, "sku_code")
        if not plu_code or not sku_code:
            continue

        skus = query_collection("skus", filters=[("sku_code", "==", sku_code)], limit=1)
        if not skus:
            continue

        existing = query_collection("plus", filters=[("plu_code", "==", plu_code)], limit=1)
        if not existing:
            batch_ops.append({"action": "create", "collection": "plus", "doc_id": str(_uuid.uuid4()), "data": {
                "plu_code": plu_code, "sku_id": skus[0].get("id", ""),
            }})
            counts["plus"] += 1

    if batch_ops:
        batch_write(batch_ops)
        batch_ops = []

    # --- Prices ---
    for price_el in root.findall(".//PRICE"):
        sku_code = _text(price_el, "sku_code")
        store_id_str = _text(price_el, "store_id")
        if not sku_code or not store_id_str:
            continue

        skus = query_collection("skus", filters=[("sku_code", "==", sku_code)], limit=1)
        if not skus:
            continue

        price_incl = float(_text(price_el, "price_incl_tax") or "0")
        price_excl = float(_text(price_el, "price_excl_tax") or "0")
        price_unit = int(_text(price_el, "price_unit") or "1")
        valid_from = (_parse_date(_text(price_el, "price_frdate")) or date.today()).isoformat()
        valid_to = (_parse_date(_text(price_el, "price_todate")) or date(2099, 12, 31)).isoformat()

        batch_ops.append({"action": "create", "collection": "prices", "doc_id": str(_uuid.uuid4()), "data": {
            "sku_id": skus[0].get("id", ""), "store_id": store_id_str,
            "price_incl_tax": price_incl, "price_excl_tax": price_excl,
            "price_unit": price_unit, "valid_from": valid_from, "valid_to": valid_to,
        }})
        counts["prices"] += 1

    if batch_ops:
        batch_write(batch_ops)
        batch_ops = []

    # --- Promotions ---
    for promo_el in root.findall(".//PROMO"):
        disc_id = _text(promo_el, "disc_id")
        sku_code = _text(promo_el, "sku_code")
        if not disc_id:
            continue

        sku_id = None
        if sku_code:
            skus = query_collection("skus", filters=[("sku_code", "==", sku_code)], limit=1)
            if skus:
                sku_id = skus[0].get("id")

        batch_ops.append({"action": "create", "collection": "promotions", "doc_id": str(_uuid.uuid4()), "data": {
            "disc_id": disc_id, "sku_id": sku_id,
            "line_type": _text(promo_el, "line_type") or "SKU",
            "disc_method": _text(promo_el, "disc_method") or "PERCENT",
            "disc_value": float(_text(promo_el, "disc_value") or "0"),
        }})
        counts["promotions"] += 1

    if batch_ops:
        batch_write(batch_ops)

    return DataResponse(data=counts)


@router.get("/export/cag-xml/{store_id}")
async def export_cag_xml(
    store_id: UUID,
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Export all SKUs for a store in CAG XML format."""
    root_el = ET.Element("CAG_EXPORT")
    root_el.set("store_id", str(store_id))

    # --- Categories ---
    categories = query_collection("categories", filters=[("store_id", "==", str(store_id))])
    cats_el = ET.SubElement(root_el, "CATEGORIES")
    cat_map = {c.get("id"): c for c in categories}

    for cat in categories:
        catg_el = ET.SubElement(cats_el, "CATG")
        ET.SubElement(catg_el, "child_catg_code").text = cat.get("catg_code", "")
        ET.SubElement(catg_el, "catg_desc").text = cat.get("description", "")
        ET.SubElement(catg_el, "cag_catg_code").text = cat.get("cag_catg_code", "")
        ET.SubElement(catg_el, "store_id").text = str(store_id)
        parent_code = ""
        if cat.get("parent_id") and cat["parent_id"] in cat_map:
            parent_code = cat_map[cat["parent_id"]].get("catg_code", "")
        ET.SubElement(catg_el, "parent_catg_code").text = parent_code

    # --- SKUs ---
    skus = query_collection("skus", filters=[("store_id", "==", str(store_id))])
    skus_el = ET.SubElement(root_el, "SKUS")
    sku_map = {s.get("id"): s for s in skus}

    for sku in skus:
        sku_el = ET.SubElement(skus_el, "SKU")
        ET.SubElement(sku_el, "sku_code").text = sku.get("sku_code", "")
        ET.SubElement(sku_el, "sku_desc").text = sku.get("description", "")
        ET.SubElement(sku_el, "cost_price").text = str(sku.get("cost_price", ""))
        ET.SubElement(sku_el, "tax_code").text = sku.get("tax_code", "G")
        ET.SubElement(sku_el, "gender").text = sku.get("gender", "")
        ET.SubElement(sku_el, "age_group").text = sku.get("age_group", "")
        ET.SubElement(sku_el, "use_stock").text = "Y" if sku.get("use_stock") else "N"
        ET.SubElement(sku_el, "block_sales").text = "Y" if sku.get("block_sales") else "N"
        ET.SubElement(sku_el, "store_id").text = str(store_id)

        catg_code = ""
        if sku.get("category_id") and sku["category_id"] in cat_map:
            catg_code = cat_map[sku["category_id"]].get("catg_code", "")
        ET.SubElement(sku_el, "sku_catg_tenant").text = catg_code

        brand_name = ""
        if sku.get("brand_id"):
            brand = get_document("brands", sku["brand_id"])
            if brand:
                brand_name = brand.get("name", "")
        ET.SubElement(sku_el, "brand").text = brand_name

    # --- PLUs ---
    plus_el = ET.SubElement(root_el, "PLUS")
    for sku in skus:
        plus = query_collection("plus", filters=[("sku_id", "==", sku.get("id", ""))])
        for plu in plus:
            plu_el = ET.SubElement(plus_el, "PLU")
            ET.SubElement(plu_el, "plu_code").text = plu.get("plu_code", "")
            ET.SubElement(plu_el, "sku_code").text = sku.get("sku_code", "")

    # --- Prices ---
    prices_el = ET.SubElement(root_el, "PRICES")
    prices = query_collection("prices", filters=[("store_id", "==", str(store_id))])

    for price in prices:
        price_el = ET.SubElement(prices_el, "PRICE")
        sku_code = sku_map.get(price.get("sku_id", ""), {}).get("sku_code", "")
        ET.SubElement(price_el, "sku_code").text = sku_code
        ET.SubElement(price_el, "store_id").text = str(store_id)
        ET.SubElement(price_el, "price_incl_tax").text = str(price.get("price_incl_tax", 0))
        ET.SubElement(price_el, "price_excl_tax").text = str(price.get("price_excl_tax", 0))
        ET.SubElement(price_el, "price_unit").text = str(price.get("price_unit", 1))
        ET.SubElement(price_el, "price_frdate").text = str(price.get("valid_from", ""))
        ET.SubElement(price_el, "price_todate").text = str(price.get("valid_to", ""))

    # --- Promotions ---
    promos_el = ET.SubElement(root_el, "PROMOTIONS")
    promos = query_collection("promotions")

    for promo in promos:
        promo_el = ET.SubElement(promos_el, "PROMO")
        ET.SubElement(promo_el, "disc_id").text = promo.get("disc_id", "")
        sku_code = ""
        if promo.get("sku_id") and promo["sku_id"] in sku_map:
            sku_code = sku_map[promo["sku_id"]].get("sku_code", "")
        ET.SubElement(promo_el, "sku_code").text = sku_code
        ET.SubElement(promo_el, "line_type").text = promo.get("line_type", "SKU")
        ET.SubElement(promo_el, "disc_method").text = promo.get("disc_method", "PERCENT")
        ET.SubElement(promo_el, "disc_value").text = str(promo.get("disc_value", 0))

    xml_bytes = ET.tostring(root_el, encoding="unicode", xml_declaration=False)
    xml_output = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    return Response(
        content=xml_output,
        media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=cag_export_{store_id}.xml"},
    )
