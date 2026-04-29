#!/usr/bin/env python3
"""
Export channel-specific product catalogs from the master product list.

Generates:
  - Amazon Seller Central flat file (CSV)
  - Google Merchant Center product feed (JSON-LD / Atom XML)
  - NEC POS item master import (XML)

Usage:
  python export_channel_catalogs.py
  python export_channel_catalogs.py --input data/master_product_list.json
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = "data/master_product_list.json"
DEFAULT_EXPORT_DIR = "data/exports"


# ── Amazon Seller Central flat file ──────────────────────────────────────────

AMAZON_HEADERS = [
    "sku", "product-id", "product-id-type", "item-name", "item-description",
    "brand", "manufacturer", "part-number", "model-number",
    "standard-price", "quantity", "product-tax-code",
    "item-type", "main-image-url", "parent-child",
    "variation-theme", "color", "material-type",
    "department", "recommended-browse-nodes",
]


def export_amazon_csv(products: list[dict[str, Any]], output_dir: Path) -> Path:
    """Export Amazon Seller Central flat file format."""
    path = output_dir / "amazon_catalog.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AMAZON_HEADERS, delimiter="\t")
        writer.writeheader()
        for p in products:
            if not p.get("amazon_sku"):
                continue
            writer.writerow({
                "sku": p["amazon_sku"],
                "product-id": p.get("nec_plu", ""),
                "product-id-type": "EAN" if p.get("nec_plu") else "",
                "item-name": p.get("description", ""),
                "item-description": p.get("long_description", "")[:2000],
                "brand": "Victoria Enso",
                "manufacturer": "Victoria Enso",
                "part-number": p.get("internal_code", ""),
                "model-number": p.get("sku_code", ""),
                "standard-price": p.get("retail_price") or "",
                "quantity": p.get("qty_on_hand") or 0,
                "product-tax-code": "A_GEN_TAX",
                "item-type": _amazon_item_type(p.get("product_type", "")),
                "main-image-url": "",
                "parent-child": "",
                "variation-theme": "",
                "color": "",
                "material-type": p.get("material", ""),
                "department": "womens" if p.get("product_type") in ("Bracelet", "Necklace", "Ring", "Pendant", "Earring") else "unisex",
                "recommended-browse-nodes": _amazon_browse_node(p.get("product_type", "")),
            })
    return path


def _amazon_item_type(product_type: str) -> str:
    return {
        "Bracelet": "fine-bracelets",
        "Necklace": "fine-necklaces",
        "Ring": "fine-rings",
        "Pendant": "fine-pendants",
        "Earring": "fine-earrings",
        "Figurine": "collectible-figurines",
        "Sculpture": "sculptures",
        "Bookend": "bookends",
        "Bowl": "decorative-bowls",
        "Wall Art": "wall-art",
    }.get(product_type, "home-decor")


def _amazon_browse_node(product_type: str) -> str:
    """Amazon browse node IDs for Singapore marketplace."""
    return {
        "Bracelet": "3887811",
        "Necklace": "3887851",
        "Ring": "3887871",
        "Pendant": "3887861",
        "Earring": "3887831",
        "Figurine": "3743981",
        "Sculpture": "3743991",
        "Wall Art": "3744041",
    }.get(product_type, "3744001")


# ── Google Merchant Center feed ──────────────────────────────────────────────

def export_google_merchant_json(products: list[dict[str, Any]], output_dir: Path) -> Path:
    """Export Google Merchant Center product feed as JSON-LD."""
    path = output_dir / "google_merchant_feed.json"
    items = []
    for p in products:
        if not p.get("google_product_id"):
            continue
        item = {
            "@context": "https://schema.org/",
            "@type": "Product",
            "productID": p["google_product_id"],
            "sku": p.get("sku_code", ""),
            "gtin13": p.get("nec_plu", ""),
            "name": p.get("description", ""),
            "description": p.get("long_description", "")[:5000],
            "brand": {"@type": "Brand", "name": "Victoria Enso"},
            "material": p.get("material", ""),
            "category": p.get("google_product_category", "") or _google_category(p.get("product_type", "")),
            "offers": {
                "@type": "Offer",
                "priceCurrency": "SGD",
                "price": p.get("retail_price") or 0,
                "availability": "https://schema.org/InStock" if (p.get("qty_on_hand") or 0) > 0 else "https://schema.org/OutOfStock",
                "itemCondition": "https://schema.org/NewCondition",
                "seller": {"@type": "Organization", "name": "Victoria Enso"},
            },
            "additionalProperty": [
                {"@type": "PropertyValue", "name": "internal_code", "value": p.get("internal_code", "")},
                {"@type": "PropertyValue", "name": "product_type", "value": p.get("product_type", "")},
            ],
        }
        items.append(item)

    feed = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_items": len(items),
        "items": items,
    }
    path.write_text(json.dumps(feed, indent=2, ensure_ascii=False))
    return path


def _google_category(product_type: str) -> str:
    """Google product taxonomy categories."""
    return {
        "Bracelet": "Apparel & Accessories > Jewelry > Bracelets",
        "Necklace": "Apparel & Accessories > Jewelry > Necklaces",
        "Ring": "Apparel & Accessories > Jewelry > Rings",
        "Pendant": "Apparel & Accessories > Jewelry > Necklaces",
        "Earring": "Apparel & Accessories > Jewelry > Earrings",
        "Figurine": "Home & Garden > Decor > Figurines",
        "Sculpture": "Home & Garden > Decor > Sculptures",
        "Bookend": "Home & Garden > Decor > Bookends",
        "Bowl": "Home & Garden > Decor > Decorative Bowls",
        "Wall Art": "Home & Garden > Decor > Wall Art",
        "Vase": "Home & Garden > Decor > Vases",
    }.get(product_type, "Home & Garden > Decor")


# ── NEC POS item master import ───────────────────────────────────────────────

def export_nec_pos_xml(products: list[dict[str, Any]], output_dir: Path) -> Path:
    """Export NEC POS item master import file (XML).

    NEC POS systems typically accept item master data in XML format with
    fields for PLU, department, description, price, and tax code.
    """
    path = output_dir / "nec_pos_items.xml"
    root = ET.Element("ItemMaster")
    root.set("xmlns", "urn:nec:pos:itemmaster:v1")
    root.set("generated", time.strftime("%Y-%m-%dT%H:%M:%S"))
    root.set("count", str(len(products)))

    for p in products:
        item = ET.SubElement(root, "Item")
        ET.SubElement(item, "PLUCode").text = p.get("nec_plu", "")
        ET.SubElement(item, "SKUCode").text = p.get("sku_code", "")[:16]
        ET.SubElement(item, "InternalCode").text = p.get("internal_code", "")
        ET.SubElement(item, "Description").text = (p.get("description", "") or "")[:40]
        ET.SubElement(item, "LongDescription").text = (p.get("description", "") or "")[:60]
        ET.SubElement(item, "Department").text = _nec_department(p.get("product_type", ""))
        ET.SubElement(item, "DepartmentCode").text = _nec_dept_code(p.get("product_type", ""))
        ET.SubElement(item, "Price").text = str(p.get("retail_price") or "0.00")
        ET.SubElement(item, "CostPrice").text = str(p.get("cost_price") or "0.00")
        ET.SubElement(item, "TaxCode").text = "G"  # GST
        ET.SubElement(item, "TaxRate").text = "9"  # SG GST 9%
        ET.SubElement(item, "StockQty").text = str(p.get("qty_on_hand") or 0)
        ET.SubElement(item, "Material").text = p.get("material", "")
        ET.SubElement(item, "Brand").text = "Victoria Enso"
        ET.SubElement(item, "Status").text = "A"  # Active

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(path), encoding="unicode", xml_declaration=True)
    return path


def _nec_department(product_type: str) -> str:
    return {
        "Bracelet": "Jewellery",
        "Necklace": "Jewellery",
        "Ring": "Jewellery",
        "Pendant": "Jewellery",
        "Earring": "Jewellery",
        "Figurine": "Home Decor",
        "Sculpture": "Home Decor",
        "Bookend": "Home Decor",
        "Bowl": "Home Decor",
        "Wall Art": "Home Decor",
        "Vase": "Home Decor",
    }.get(product_type, "General")


def _nec_dept_code(product_type: str) -> str:
    return {
        "Bracelet": "JWL001",
        "Necklace": "JWL002",
        "Ring": "JWL003",
        "Pendant": "JWL004",
        "Earring": "JWL005",
        "Figurine": "HOM001",
        "Sculpture": "HOM002",
        "Bookend": "HOM003",
        "Bowl": "HOM004",
        "Wall Art": "HOM005",
        "Vase": "HOM006",
    }.get(product_type, "GEN001")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Export channel catalogs")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", default=DEFAULT_EXPORT_DIR)
    args = parser.parse_args()

    repo_root = REPO_ROOT

    def _repo_path(p: str | Path) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()

    input_path = _repo_path(args.input)
    output_dir = _repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(input_path.read_text())
    products = data.get("products", [])
    print(f"Loaded {len(products)} products from {input_path}")

    # Export all formats
    amazon_path = export_amazon_csv(products, output_dir)
    print(f"  Amazon CSV         -> {amazon_path}")

    google_path = export_google_merchant_json(products, output_dir)
    print(f"  Google Merchant    -> {google_path}")

    nec_path = export_nec_pos_xml(products, output_dir)
    print(f"  NEC POS XML        -> {nec_path}")

    print(f"\nAll exports complete: {output_dir}")


if __name__ == "__main__":
    main()
