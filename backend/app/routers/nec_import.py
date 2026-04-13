from __future__ import annotations

import xml.etree.ElementTree as ET

import defusedxml.ElementTree as SafeET
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.inventory import SKU
from app.models.order import Order, OrderItem, OrderSource, OrderStatus
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/import", tags=["import"])


class NECImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = []


@router.post("/nec-sales", response_model=NECImportResult)
async def import_nec_sales(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse NEC POS XML sales feed and create orders.

    Expects XML with <SalesExport><Transaction>... structure.
    Skips duplicate transaction IDs for idempotency.
    """
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
    try:
        root = SafeET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {e}")

    transactions = root.findall("Transaction")
    if not transactions:
        raise HTTPException(status_code=400, detail="No Transaction elements found in XML")

    imported = 0
    skipped = 0
    errors: list[str] = []

    for txn in transactions:
        txn_id = _text(txn, "TransactionId")
        if not txn_id:
            errors.append("Transaction missing TransactionId, skipped")
            continue

        # Check for duplicate by order_number
        order_number = f"NEC-{txn_id}"
        existing = await db.execute(
            select(Order).where(Order.order_number == order_number)
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        # Parse transaction fields
        try:
            timestamp_str = _text(txn, "Timestamp")
            store_id_str = _text(txn, "StoreId")
            cashier_id = _text(txn, "CashierId")
            payment_method = _text(txn, "PaymentMethod") or "cash"
            payment_ref = _text(txn, "PaymentRef")
            subtotal = float(_text(txn, "Subtotal") or "0")
            discount_total = float(_text(txn, "DiscountTotal") or "0")
            tax_total = float(_text(txn, "TaxTotal") or "0")
            grand_total = float(_text(txn, "GrandTotal") or "0")

            order_date = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.now(timezone.utc)

            # Look up the store by matching store name/location or use direct UUID
            # For NEC imports, StoreId in XML is a store identifier string.
            # We need to find the matching store. Try UUID first, then fall back.
            from app.models.store import Store
            store_id: Optional[UUID] = None
            try:
                store_id = UUID(store_id_str)
                store_check = await db.execute(
                    select(Store).where(Store.id == store_id)
                )
                if store_check.scalar_one_or_none() is None:
                    store_id = None
            except (ValueError, TypeError):
                store_id = None

            if store_id is None:
                # Try to find store by name containing the store_id_str
                store_check = await db.execute(
                    select(Store).where(Store.name == store_id_str)
                )
                store_obj = store_check.scalar_one_or_none()
                if store_obj is not None:
                    store_id = store_obj.id
                else:
                    errors.append(f"Transaction {txn_id}: store '{store_id_str}' not found, skipped")
                    continue

            order = Order(
                order_number=order_number,
                store_id=store_id,
                staff_id=None,
                order_date=order_date,
                subtotal=subtotal,
                discount_total=discount_total,
                tax_total=tax_total,
                grand_total=grand_total,
                payment_method=payment_method.lower(),
                payment_ref=payment_ref,
                status=OrderStatus.completed,
                source=OrderSource.nec_pos,
            )
            db.add(order)
            await db.flush()

            # Parse line items
            items_el = txn.find("Items")
            if items_el is not None:
                for item_el in items_el.findall("Item"):
                    sku_code = _text(item_el, "SKUCode")
                    qty = int(_text(item_el, "Quantity") or "1")
                    unit_price = float(_text(item_el, "UnitPrice") or "0")
                    discount = float(_text(item_el, "Discount") or "0")
                    line_total = float(_text(item_el, "LineTotal") or "0")

                    # Look up SKU by code
                    sku_result = await db.execute(
                        select(SKU).where(SKU.sku_code == sku_code, SKU.store_id == store_id)
                    )
                    sku = sku_result.scalar_one_or_none()
                    if sku is None:
                        errors.append(
                            f"Transaction {txn_id}: SKU '{sku_code}' not found, item skipped"
                        )
                        continue

                    order_item = OrderItem(
                        order_id=order.id,
                        sku_id=sku.id,
                        qty=qty,
                        unit_price=unit_price,
                        discount=discount,
                        line_total=line_total,
                    )
                    db.add(order_item)

            imported += 1
        except Exception as e:
            errors.append(f"Transaction {txn_id}: {str(e)}")
            continue

    await db.flush()
    return NECImportResult(imported=imported, skipped=skipped, errors=errors)


def _text(element: ET.Element, tag: str) -> Optional[str]:
    """Safely extract text from a child element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None
