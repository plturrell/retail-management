from __future__ import annotations

import uuid as _uuid
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as SafeET
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import get_firestore_db
from app.firestore_helpers import create_document, get_document, query_collection, batch_write
from app.auth.dependencies import get_current_user
from app.services.store_identity import resolve_firestore_store_document

router = APIRouter(prefix="/api/import", tags=["import"])


class NECImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = []


@router.post("/nec-sales", response_model=NECImportResult)
async def import_nec_sales(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: FirestoreClient = Depends(get_firestore_db),
):
    """Parse NEC POS XML sales feed and create orders."""
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
    batch_ops = []

    for txn in transactions:
        txn_id = _text(txn, "TransactionId")
        if not txn_id:
            errors.append("Transaction missing TransactionId, skipped")
            continue

        order_number = f"NEC-{txn_id}"

        try:
            timestamp_str = _text(txn, "Timestamp")
            store_id_str = _text(txn, "StoreId")
            payment_method = _text(txn, "PaymentMethod") or "cash"
            payment_ref = _text(txn, "PaymentRef")
            subtotal = float(_text(txn, "Subtotal") or "0")
            discount_total = float(_text(txn, "DiscountTotal") or "0")
            tax_total = float(_text(txn, "TaxTotal") or "0")
            grand_total = float(_text(txn, "GrandTotal") or "0")

            order_date = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.now(timezone.utc)

            store_doc = resolve_firestore_store_document(store_id_str)
            if store_doc is None:
                errors.append(f"Transaction {txn_id}: store '{store_id_str}' not found, skipped")
                continue
            store_id = str(store_doc.get("id", ""))

            existing = query_collection(
                f"stores/{store_id}/orders",
                filters=[("order_number", "==", order_number)],
                limit=1,
            )
            if existing:
                skipped += 1
                continue

            now = datetime.now(timezone.utc)
            order_doc_id = str(_uuid.uuid4())

            # Parse line items
            items_data = []
            items_el = txn.find("Items")
            if items_el is not None:
                for item_el in items_el.findall("Item"):
                    sku_code = _text(item_el, "SKUCode")
                    qty = int(_text(item_el, "Quantity") or "1")
                    unit_price = float(_text(item_el, "UnitPrice") or "0")
                    discount = float(_text(item_el, "Discount") or "0")
                    line_total = float(_text(item_el, "LineTotal") or "0")

                    skus = query_collection("skus", filters=[("sku_code", "==", sku_code), ("store_id", "==", store_id)], limit=1)
                    if not skus:
                        errors.append(f"Transaction {txn_id}: SKU '{sku_code}' not found, item skipped")
                        continue

                    items_data.append({
                        "id": str(_uuid.uuid4()),
                        "sku_id": skus[0].get("id", ""),
                        "qty": qty,
                        "unit_price": unit_price,
                        "discount": discount,
                        "line_total": line_total,
                    })

            order_data = {
                "order_number": order_number,
                "store_id": store_id,
                "staff_id": None,
                "order_date": order_date.isoformat() if isinstance(order_date, datetime) else str(order_date),
                "subtotal": subtotal,
                "discount_total": discount_total,
                "tax_total": tax_total,
                "grand_total": grand_total,
                "payment_method": payment_method.lower(),
                "payment_ref": payment_ref,
                "status": "completed",
                "source": "nec_pos",
                "items": items_data,
                "created_at": now,
                "updated_at": now,
            }

            batch_ops.append({
                "action": "create",
                "collection": f"stores/{store_id}/orders",
                "doc_id": order_doc_id,
                "data": order_data,
            })
            imported += 1
        except Exception as e:
            errors.append(f"Transaction {txn_id}: {str(e)}")
            continue

    if batch_ops:
        batch_write(batch_ops)

    return NECImportResult(imported=imported, skipped=skipped, errors=errors)


def _text(element: ET.Element, tag: str) -> Optional[str]:
    """Safely extract text from a child element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None
