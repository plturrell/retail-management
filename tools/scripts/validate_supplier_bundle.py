#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_supplier_folder(folder: Path) -> None:
    bundle_path = folder / "supplier_bundle.json"
    profile_path = folder / "supplier_profile.json"

    _assert(bundle_path.exists(), f"Missing bundle file: {bundle_path}")
    _assert(profile_path.exists(), f"Missing supplier profile: {profile_path}")

    bundle = _load_json(bundle_path)
    profile = _load_json(profile_path)

    _assert(bundle.get("schema_version") == 1, "Unsupported schema_version in supplier bundle")
    _assert(bundle.get("supplier", {}).get("id") == profile.get("id"), "Supplier ID mismatch between bundle and profile")

    for catalog in bundle.get("catalog_sources", []):
        file_path = folder / catalog["file"]
        _assert(file_path.exists(), f"Missing catalog source: {file_path}")

    order_record_paths = {path.name: folder / path for path in [Path(item) for item in profile.get("order_records", [])]}
    for order in bundle.get("orders", []):
        order_number = order["order_number"]
        order_path = folder / "orders" / f"{order_number}.json"
        _assert(order_path.exists(), f"Missing order record: {order_path}")
        order_record = _load_json(order_path)
        _assert(order_record.get("order_number") == order_number, f"Order number mismatch in {order_path}")
        _assert(
            order_record.get("source_document_total_amount") == order.get("source_document_total_amount"),
            f"Order total mismatch for {order_number}",
        )
        for document in order.get("documents", []):
            file_path = folder / document["file"]
            _assert(file_path.exists(), f"Missing order document: {file_path}")
        _assert(order_path.name in order_record_paths, f"Order record {order_path.name} is not referenced by supplier_profile.json")
        line_items = order_record.get("line_items", [])
        line_total = sum(int(item.get("line_total_cny", 0) or 0) for item in line_items)
        charge_total = sum(int(item.get("amount", 0) or 0) for item in order_record.get("charges", []))
        _assert(
            line_total + charge_total == int(order_record.get("source_document_total_amount", 0) or 0),
            f"Order lines plus charges do not reconcile for {order_number}",
        )

    product_candidates_file = profile.get("product_candidates_file")
    if product_candidates_file:
        product_candidates_path = folder / product_candidates_file
        _assert(product_candidates_path.exists(), f"Missing product candidates file: {product_candidates_path}")
        product_candidates = _load_json(product_candidates_path)
        _assert(
            product_candidates.get("supplier_id") == profile.get("id"),
            "Supplier ID mismatch between product candidates and profile",
        )

    catalog_products_file = profile.get("catalog_products_file")
    if catalog_products_file:
        catalog_products_path = folder / catalog_products_file
        _assert(catalog_products_path.exists(), f"Missing catalog products file: {catalog_products_path}")
        catalog_products = _load_json(catalog_products_path)
        _assert(
            catalog_products.get("supplier_id") == profile.get("id"),
            "Supplier ID mismatch between catalog products and profile",
        )

    print(f"{folder}: OK")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: validate_supplier_bundle.py /path/to/docs/suppliers/<supplier>", file=sys.stderr)
        return 2

    try:
        validate_supplier_folder(Path(argv[1]).resolve())
    except Exception as exc:  # pragma: no cover - CLI error surface
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
