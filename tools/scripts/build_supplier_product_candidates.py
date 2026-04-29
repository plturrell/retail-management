#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _catalog_index(catalog_products: list[dict]) -> dict[str, list[dict]]:
    indexed: dict[str, list[dict]] = {}
    for product in catalog_products:
        for code in product.get("supplier_item_codes", []):
            indexed.setdefault(code, []).append(product)
    return indexed


def _catalog_lookup_keys(code: str) -> list[str]:
    keys = [code]
    ascii_code_match = re.match(r"[A-Za-z]+\d+[A-Za-z]?", code)
    if ascii_code_match:
        ascii_code = ascii_code_match.group(0)
        if ascii_code not in keys:
            keys.append(ascii_code)

    base_code_match = re.match(r"[A-Za-z]+\d+", code)
    if base_code_match:
        base_code = base_code_match.group(0)
        if base_code not in keys:
            keys.append(base_code)
    return keys


def build_product_candidates(folder: Path) -> dict:
    profile = _load_json(folder / "supplier_profile.json")
    catalog_products_file = profile.get("catalog_products_file")
    catalog_products = []
    if catalog_products_file and (folder / catalog_products_file).exists():
        catalog_products = _load_json(folder / catalog_products_file).get("products", [])
    indexed_catalog = _catalog_index(catalog_products)
    products: dict[str, dict] = {}
    uncoded_lines: list[dict] = []

    for record_path in profile.get("order_records", []):
        order = _load_json(folder / record_path)
        order_number = order["order_number"]
        for item in order.get("line_items", []):
            code = item.get("supplier_item_code")
            if not code:
                uncoded_lines.append(
                    {
                        "order_number": order_number,
                        "source_line_number": item.get("source_line_number"),
                        "display_name": item.get("display_name"),
                        "line_total_cny": item.get("line_total_cny"),
                    }
                )
                continue
            product = products.setdefault(
                code,
                {
                    "supplier_item_code": code,
                    "supplier_name": profile["name"],
                    "supplier_id": profile["id"],
                    "inventory_type": "purchased",
                    "sourcing_strategy": "supplier_premade",
                    "default_unit_cost_cny": item.get("unit_cost_cny"),
                    "material_descriptions": [],
                    "observed_sizes": [],
                    "source_orders": [],
                    "source_line_numbers": [],
                    "notes": [],
                    "catalog_matches": [],
                    "catalog_match_count": 0,
                    "import_status": "needs_catalog_match",
                },
            )
            if not product.get("default_unit_cost_cny"):
                product["default_unit_cost_cny"] = item.get("unit_cost_cny")
            material = item.get("material_description")
            if material and material not in product["material_descriptions"]:
                product["material_descriptions"].append(material)
            size = item.get("size")
            if size and size not in product["observed_sizes"]:
                product["observed_sizes"].append(size)
            if order_number not in product["source_orders"]:
                product["source_orders"].append(order_number)
            line_ref = f"{order_number}:{item.get('source_line_number')}"
            if item.get("line_position"):
                line_ref = f"{line_ref}{item['line_position']}"
            if line_ref not in product["source_line_numbers"]:
                product["source_line_numbers"].append(line_ref)
            if item.get("note") and item["note"] not in product["notes"]:
                product["notes"].append(item["note"])

    for code, product in products.items():
        catalog_matches: list[dict] = []
        matched_via = "exact"
        for lookup_key in _catalog_lookup_keys(code):
            catalog_matches = indexed_catalog.get(lookup_key, [])
            if catalog_matches:
                matched_via = "exact" if lookup_key == code else "base_code"
                break
        product["catalog_matches"] = [
            {
                "catalog_product_id": match["catalog_product_id"],
                "catalog_file": match["catalog_file"],
                "sheet_name": match["sheet_name"],
                "display_name": match.get("display_name"),
                "size": match.get("size"),
                "materials": match.get("materials"),
                "price_label": match.get("price_label"),
                "price_options_cny": match.get("price_options_cny", []),
                "raw_model": match.get("raw_model"),
                "match_strategy": matched_via,
            }
            for match in catalog_matches
        ]
        product["catalog_match_count"] = len(product["catalog_matches"])
        product["import_status"] = "catalog_matched" if product["catalog_matches"] else "needs_catalog_match"

    return {
        "schema_version": 2,
        "supplier_id": profile["id"],
        "supplier_name": profile["name"],
        "source_order_records": profile.get("order_records", []),
        "catalog_products_file": catalog_products_file,
        "matched_catalog_products": sum(1 for item in products.values() if item["catalog_match_count"] > 0),
        "unmatched_supplier_codes": sorted(code for code, item in products.items() if item["catalog_match_count"] == 0),
        "products": sorted(products.values(), key=lambda item: item["supplier_item_code"]),
        "uncoded_order_lines": uncoded_lines,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: build_supplier_product_candidates.py /path/to/docs/suppliers/<supplier>", file=sys.stderr)
        return 2

    folder = Path(argv[1]).resolve()
    output_path = folder / "product_candidates.json"
    data = build_product_candidates(folder)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
