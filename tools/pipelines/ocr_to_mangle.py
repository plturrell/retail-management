"""
ocr_to_mangle.py  (v3)
----------------------
Converts OCR-extracted JSON purchase orders (from ocr_outputs/) into
Google Mangle .mangle fact files (in mangle_facts/).

Robust field resolution handles all key-name variants emitted by Gemini
across different runs (snake_case, camelCase, abbreviated, nested, etc.)

Currency: all CNY (yuan) prices are also output in SGD at a fixed rate.
  1 SGD = CNY_SGD_RATE CNY

Fact schemas:
  pos_order(order_id, customer, date, total_cny, freight_cny, total_sgd, freight_sgd, status).
  pos_item(order_id, item_no, code, material, size, price_cny, qty, amount_cny, price_sgd, amount_sgd).
"""

import os
import json
import re
from pathlib import Path

from paths import MANGLE_FACTS_DIR, OCR_OUTPUTS_DIR

OCR_DIR = str(OCR_OUTPUTS_DIR)
OUT_DIR = str(MANGLE_FACTS_DIR)
OUT_FILE = os.path.join(OUT_DIR, "pos_orders.mangle")

# Currency conversion — update this rate as needed
# 1 SGD = CNY_SGD_RATE CNY  (user-specified: 5.34)
CNY_SGD_RATE = 5.34


# ── value helpers ─────────────────────────────────────────────────────────────

def mangle_str(v):
    """Wrap a value in Mangle string quotes, escaping inner quotes."""
    if v is None:
        return '"null"'
    s = str(v).replace('"', '\\"').replace('\n', ' ').strip()
    return f'"{s}"'

def mangle_num(v):
    """Return a Mangle numeric literal, falling back to 0."""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return "0"

def mangle_sgd(cny_val):
    """Convert a CNY string/number to an SGD float literal (2 dp)."""
    try:
        sgd = round(float(cny_val) / CNY_SGD_RATE, 2)
        return str(sgd)
    except (TypeError, ValueError):
        return "0.0"


# ── multi-key field resolver ──────────────────────────────────────────────────

def pick(d: dict, *keys, default=None):
    """
    Try each string key name in order against dict d.
    Keys support dot notation for nested access: "summary.total".
    Returns the first non-None, non-empty-string value found.
    """
    for key in keys:
        if not isinstance(key, str):
            continue
        parts = key.split(".")
        val = d
        for p in parts:
            if not isinstance(val, dict):
                val = None
                break
            val = val.get(p)
        if val is not None and str(val).strip() not in ("", "null", "None"):
            return val
    return default

def pick_any(dicts: list, *keys, default=None):
    """Try pick() across multiple dicts, returning the first hit."""
    for d in dicts:
        if not isinstance(d, dict):
            continue
        result = pick(d, *keys, default=None)
        if result is not None:
            return result
    return default

def get_items(data: dict) -> list:
    """Return the items list regardless of which key was used."""
    for key in ("order_items", "items", "lineItems", "line_items", "products"):
        v = data.get(key)
        if isinstance(v, list) and v:
            return v
    return []

def get_header(data: dict) -> dict:
    """Return the header sub-dict or fall back to the top-level dict."""
    for key in ("header", "orderInfo", "order_info", "info"):
        v = data.get(key)
        if isinstance(v, dict):
            return v
    return data  # top-level is the header

def extract_english_material(item: dict) -> str:
    """
    Pull the English portion of the material string from whatever key holds it.
    Strips leading CJK characters to isolate the English description.
    """
    raw = pick(item,
               "material_english", "materialEnglish",
               "material", "description", "item_description") or ""
    # Remove leading CJK block + connectors
    english = re.sub(r'^[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef/\s,、]+', '', str(raw)).strip()
    return english if english else str(raw).strip()


# ── per-file conversion ───────────────────────────────────────────────────────

def convert_order(data: dict, doc_id: str, f):
    """Write pos_order and pos_item facts for one JSON order document."""

    header  = get_header(data)
    summary = data.get("summary", {}) or {}
    sources = [header, data, summary]   # search order for field resolution

    # ── Header fields ────────────────────────────────────────────────────────
    order_no = pick_any(sources,
                        "order_number", "orderNumber", "order_no", "orderNo",
                        "invoice_number", "invoiceNumber",
                        default=doc_id)

    customer = pick_any(sources,
                        "ordering_unit", "orderingUnit",
                        "customer", "customerName", "buyer",
                        "order_unit", "client",
                        default="unknown")

    date = pick_any(sources,
                    "date", "order_date", "orderDate",
                    "invoice_date", "created_at",
                    default="unknown")

    payment_status = pick_any(sources,
                              "payment_status", "paymentStatus",
                              "status", "payment",
                              default="unknown")

    freight_yuan = mangle_num(
        pick_any(sources,
                 "sea_freight_yuan", "seaFreightYuan",
                 "freight_yuan", "freightYuan", "shipping_cost",
                 default=0)
    )

    # ── Total: explicit field or compute from items ──────────────────────────
    raw_total = pick_any(sources,
                         "total_amount_yuan", "totalAmountYuan",
                         "total_yuan", "totalYuan", "grand_total", "total")
    if raw_total:
        total_yuan = mangle_num(raw_total)
    else:
        items_list = get_items(data)
        computed = sum(
            float(pick(it, "amount_yuan", "amountYuan", "amount",
                       "total", "subtotal", default=0) or 0)
            for it in items_list
        )
        total_yuan = mangle_num(computed)
        if computed > 0:
            print(f"  (computed total from items: ¥{int(computed)})")

    order_id = mangle_str(f"{doc_id}_{order_no}")

    # SGD equivalents
    total_cny_raw   = float(total_yuan)
    freight_cny_raw = float(freight_yuan)
    total_sgd   = mangle_sgd(total_cny_raw)
    freight_sgd = mangle_sgd(freight_cny_raw)

    f.write(
        f"pos_order({order_id}, {mangle_str(customer)}, {mangle_str(date)}, "
        f"{total_yuan}, {freight_yuan}, {total_sgd}, {freight_sgd}, "
        f"{mangle_str(payment_status)}).\n"
    )

    # ── Line items ───────────────────────────────────────────────────────────
    for item in get_items(data):
        item_no  = mangle_str(pick(item, "item_no", "itemNo", "serial_number",
                                   "serialNumber", "no", "line_no", default=""))
        code     = mangle_str(pick(item, "code", "sku_code", "skuCode",
                                   "product_code", "item_code", default=""))
        material = mangle_str(extract_english_material(item))
        size     = mangle_str(pick(item, "size", "dimensions", "dimension", default=""))
        price    = mangle_num(pick(item, "price_yuan", "priceYuan",
                                   "price_per_unit_yuan", "pricePerUnitYuan",
                                   "unit_price", "unitPrice", "unitPriceYuan",
                                   "price", default=0))
        qty      = mangle_num(pick(item, "quantity", "qty", "count", default=0))
        amount   = mangle_num(pick(item, "amount_yuan", "amountYuan",
                                   "amount", "total", "subtotal", default=0))

        price_sgd  = mangle_sgd(price)
        amount_sgd = mangle_sgd(amount)

        f.write(
            f"pos_item({order_id}, {item_no}, {code}, {material}, "
            f"{size}, {price}, {qty}, {amount}, {price_sgd}, {amount_sgd}).\n"
        )


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    json_files = sorted(Path(OCR_DIR).glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {OCR_DIR}")
        return

    written_orders = 0
    written_items  = 0

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Auto-generated Mangle facts from OCR purchase order images\n")
        f.write(f"# Currency: 1 SGD = {CNY_SGD_RATE} CNY (fixed rate)\n")
        f.write("# Schema:\n")
        f.write("#   pos_order(order_id, customer, date, total_cny, freight_cny, total_sgd, freight_sgd, status).\n")
        f.write("#   pos_item(order_id, item_no, code, material, size, price_cny, qty, amount_cny, price_sgd, amount_sgd).\n\n")

        for json_path in json_files:
            doc_id = json_path.stem
            print(f"Converting {json_path.name} ...")
            try:
                with open(json_path, encoding="utf-8") as jf:
                    data = json.load(jf)

                f.write(f"\n# --- {json_path.name} ---\n")
                convert_order(data, doc_id, f)

                n_items = len(get_items(data))
                written_orders += 1
                written_items  += n_items
                print(f"  -> {n_items} line items written.")

            except Exception as e:
                print(f"  ERROR converting {json_path.name}: {e}")

    print(f"\nDone. Written to: {OUT_FILE}")
    print(f"  {written_orders} order(s), {written_items} item fact(s) total.")


if __name__ == "__main__":
    main()
