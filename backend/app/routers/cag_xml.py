from __future__ import annotations

import xml.etree.ElementTree as ET

import defusedxml.ElementTree as SafeET
from datetime import date, datetime
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import Brand, Category, Inventory, PLU, Price, Promotion, SKU
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse

router = APIRouter(prefix="/api", tags=["cag-xml"])


def _text(el: ET.Element, tag: str) -> str | None:
    """Get text of a child element, or None."""
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import CAG XML file and upsert categories, SKUs, PLUs, prices, promotions."""
    content = await file.read()
    try:
        root = SafeET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {e}")

    counts = {
        "categories": 0,
        "skus": 0,
        "plus": 0,
        "prices": 0,
        "promotions": 0,
    }

    # --- Categories ---
    for catg_el in root.findall(".//CATG"):
        parent_code = _text(catg_el, "parent_catg_code")
        child_code = _text(catg_el, "child_catg_code")
        catg_desc = _text(catg_el, "catg_desc") or ""
        cag_code = _text(catg_el, "cag_catg_code")
        store_id_str = _text(catg_el, "store_id")

        if not child_code or not store_id_str:
            continue

        store_id = UUID(store_id_str)

        # Find or create
        result = await db.execute(
            select(Category).where(
                Category.catg_code == child_code,
                Category.store_id == store_id,
            )
        )
        category = result.scalar_one_or_none()

        # Resolve parent
        parent_id = None
        if parent_code:
            parent_result = await db.execute(
                select(Category).where(
                    Category.catg_code == parent_code,
                    Category.store_id == store_id,
                )
            )
            parent = parent_result.scalar_one_or_none()
            if parent:
                parent_id = parent.id

        if category:
            category.description = catg_desc
            category.cag_catg_code = cag_code
            category.parent_id = parent_id
        else:
            category = Category(
                catg_code=child_code,
                description=catg_desc,
                cag_catg_code=cag_code,
                store_id=store_id,
                parent_id=parent_id,
            )
            db.add(category)

        counts["categories"] += 1

    await db.flush()

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

        store_id = UUID(store_id_str)
        use_stock = use_stock_str in ("Y", "1", "true", "True") if use_stock_str else True
        block_sales = block_sales_str in ("Y", "1", "true", "True") if block_sales_str else False

        # Resolve category
        category_id = None
        if catg_code:
            cat_result = await db.execute(
                select(Category).where(
                    Category.catg_code == catg_code,
                    Category.store_id == store_id,
                )
            )
            cat = cat_result.scalar_one_or_none()
            if cat:
                category_id = cat.id

        # Resolve brand
        brand_id = None
        if brand_name:
            brand_result = await db.execute(
                select(Brand).where(Brand.name == brand_name)
            )
            brand = brand_result.scalar_one_or_none()
            if not brand:
                brand = Brand(name=brand_name)
                db.add(brand)
                await db.flush()
            brand_id = brand.id

        # Find or create SKU
        result = await db.execute(
            select(SKU).where(SKU.sku_code == sku_code)
        )
        sku = result.scalar_one_or_none()

        if sku:
            sku.description = sku_desc
            sku.cost_price = cost_price
            sku.category_id = category_id
            sku.brand_id = brand_id
            sku.tax_code = tax_code
            sku.gender = gender
            sku.age_group = age_group
            sku.use_stock = use_stock
            sku.block_sales = block_sales
        else:
            sku = SKU(
                sku_code=sku_code,
                description=sku_desc,
                cost_price=cost_price,
                category_id=category_id,
                brand_id=brand_id,
                tax_code=tax_code,
                gender=gender,
                age_group=age_group,
                use_stock=use_stock,
                block_sales=block_sales,
                store_id=store_id,
            )
            db.add(sku)

        counts["skus"] += 1

    await db.flush()

    # --- PLUs ---
    for plu_el in root.findall(".//PLU"):
        plu_code = _text(plu_el, "plu_code")
        sku_code = _text(plu_el, "sku_code")
        if not plu_code or not sku_code:
            continue

        sku_result = await db.execute(
            select(SKU).where(SKU.sku_code == sku_code)
        )
        sku = sku_result.scalar_one_or_none()
        if not sku:
            continue

        plu_result = await db.execute(
            select(PLU).where(PLU.plu_code == plu_code)
        )
        plu = plu_result.scalar_one_or_none()
        if not plu:
            plu = PLU(plu_code=plu_code, sku_id=sku.id)
            db.add(plu)
            counts["plus"] += 1

    await db.flush()

    # --- Prices ---
    for price_el in root.findall(".//PRICE"):
        sku_code = _text(price_el, "sku_code")
        store_id_str = _text(price_el, "store_id")
        if not sku_code or not store_id_str:
            continue

        store_id = UUID(store_id_str)

        sku_result = await db.execute(
            select(SKU).where(SKU.sku_code == sku_code)
        )
        sku = sku_result.scalar_one_or_none()
        if not sku:
            continue

        price_incl = float(_text(price_el, "price_incl_tax") or "0")
        price_excl = float(_text(price_el, "price_excl_tax") or "0")
        price_unit = int(_text(price_el, "price_unit") or "1")
        valid_from = _parse_date(_text(price_el, "price_frdate")) or date.today()
        valid_to = _parse_date(_text(price_el, "price_todate")) or date(2099, 12, 31)

        price = Price(
            sku_id=sku.id,
            store_id=store_id,
            price_incl_tax=price_incl,
            price_excl_tax=price_excl,
            price_unit=price_unit,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        db.add(price)
        counts["prices"] += 1

    await db.flush()

    # --- Promotions ---
    for promo_el in root.findall(".//PROMO"):
        disc_id = _text(promo_el, "disc_id")
        sku_code = _text(promo_el, "sku_code")
        if not disc_id:
            continue

        sku_id = None
        if sku_code:
            sku_result = await db.execute(
                select(SKU).where(SKU.sku_code == sku_code)
            )
            sku = sku_result.scalar_one_or_none()
            if sku:
                sku_id = sku.id

        line_type = _text(promo_el, "line_type") or "SKU"
        disc_method = _text(promo_el, "disc_method") or "PERCENT"
        disc_value = float(_text(promo_el, "disc_value") or "0")

        promo = Promotion(
            disc_id=disc_id,
            sku_id=sku_id,
            line_type=line_type,
            disc_method=disc_method,
            disc_value=disc_value,
        )
        db.add(promo)
        counts["promotions"] += 1

    await db.flush()

    return DataResponse(data=counts)


@router.get("/export/cag-xml/{store_id}")
async def export_cag_xml(
    store_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all SKUs for a store in CAG XML format."""
    root = ET.Element("CAG_EXPORT")
    root.set("store_id", str(store_id))

    # --- Categories ---
    cat_result = await db.execute(
        select(Category).where(Category.store_id == store_id)
    )
    categories = cat_result.scalars().all()
    cats_el = ET.SubElement(root, "CATEGORIES")
    cat_map = {c.id: c for c in categories}

    for cat in categories:
        catg_el = ET.SubElement(cats_el, "CATG")
        ET.SubElement(catg_el, "child_catg_code").text = cat.catg_code
        ET.SubElement(catg_el, "catg_desc").text = cat.description
        ET.SubElement(catg_el, "cag_catg_code").text = cat.cag_catg_code or ""
        ET.SubElement(catg_el, "store_id").text = str(store_id)
        parent_code = ""
        if cat.parent_id and cat.parent_id in cat_map:
            parent_code = cat_map[cat.parent_id].catg_code
        ET.SubElement(catg_el, "parent_catg_code").text = parent_code

    # --- SKUs ---
    sku_result = await db.execute(
        select(SKU).where(SKU.store_id == store_id)
    )
    skus = sku_result.scalars().all()
    skus_el = ET.SubElement(root, "SKUS")

    for sku in skus:
        sku_el = ET.SubElement(skus_el, "SKU")
        ET.SubElement(sku_el, "sku_code").text = sku.sku_code
        ET.SubElement(sku_el, "sku_desc").text = sku.description
        ET.SubElement(sku_el, "cost_price").text = str(sku.cost_price or "")
        ET.SubElement(sku_el, "tax_code").text = sku.tax_code
        ET.SubElement(sku_el, "gender").text = sku.gender or ""
        ET.SubElement(sku_el, "age_group").text = sku.age_group or ""
        ET.SubElement(sku_el, "use_stock").text = "Y" if sku.use_stock else "N"
        ET.SubElement(sku_el, "block_sales").text = "Y" if sku.block_sales else "N"
        ET.SubElement(sku_el, "store_id").text = str(store_id)

        # category code
        catg_code = ""
        if sku.category_id and sku.category_id in cat_map:
            catg_code = cat_map[sku.category_id].catg_code
        ET.SubElement(sku_el, "sku_catg_tenant").text = catg_code

        # brand name
        brand_name = ""
        if sku.brand:
            brand_name = sku.brand.name
        ET.SubElement(sku_el, "brand").text = brand_name

    # --- PLUs ---
    plus_el = ET.SubElement(root, "PLUS")
    for sku in skus:
        # Load PLUs
        plu_result = await db.execute(
            select(PLU).where(PLU.sku_id == sku.id)
        )
        plus = plu_result.scalars().all()
        for plu in plus:
            plu_el = ET.SubElement(plus_el, "PLU")
            ET.SubElement(plu_el, "plu_code").text = plu.plu_code
            ET.SubElement(plu_el, "sku_code").text = sku.sku_code

    # --- Prices ---
    prices_el = ET.SubElement(root, "PRICES")
    price_result = await db.execute(
        select(Price).where(Price.store_id == store_id)
    )
    prices = price_result.scalars().all()
    sku_map = {s.id: s for s in skus}

    for price in prices:
        price_el = ET.SubElement(prices_el, "PRICE")
        sku_code = sku_map[price.sku_id].sku_code if price.sku_id in sku_map else ""
        ET.SubElement(price_el, "sku_code").text = sku_code
        ET.SubElement(price_el, "store_id").text = str(store_id)
        ET.SubElement(price_el, "price_incl_tax").text = str(price.price_incl_tax)
        ET.SubElement(price_el, "price_excl_tax").text = str(price.price_excl_tax)
        ET.SubElement(price_el, "price_unit").text = str(price.price_unit)
        ET.SubElement(price_el, "price_frdate").text = price.valid_from.isoformat()
        ET.SubElement(price_el, "price_todate").text = price.valid_to.isoformat()

    # --- Promotions ---
    promos_el = ET.SubElement(root, "PROMOTIONS")
    promo_result = await db.execute(select(Promotion))
    promos = promo_result.scalars().all()

    for promo in promos:
        promo_el = ET.SubElement(promos_el, "PROMO")
        ET.SubElement(promo_el, "disc_id").text = promo.disc_id
        sku_code = ""
        if promo.sku_id and promo.sku_id in sku_map:
            sku_code = sku_map[promo.sku_id].sku_code
        ET.SubElement(promo_el, "sku_code").text = sku_code
        ET.SubElement(promo_el, "line_type").text = promo.line_type
        ET.SubElement(promo_el, "disc_method").text = promo.disc_method
        ET.SubElement(promo_el, "disc_value").text = str(promo.disc_value)

    # Serialize
    xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=False)
    xml_output = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    return Response(
        content=xml_output,
        media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=cag_export_{store_id}.xml"},
    )
