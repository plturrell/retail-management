#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

NS_MAIN = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
WORKBOOK_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def _normalize_label(value: str | None) -> str:
    return _normalize_text(value).lower()


def _slugify(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return compact.strip("-") or "item"


def _column_name(index: int) -> str:
    chars: list[str] = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        chars.append(chr(65 + remainder))
    return "".join(reversed(chars))


def _load_shared_strings(archive: ZipFile) -> list[str]:
    shared: list[str] = []
    if "xl/sharedStrings.xml" not in archive.namelist():
        return shared

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    for item in root.findall("a:si", NS_MAIN):
        text = "".join(node.text or "" for node in item.iterfind(".//a:t", NS_MAIN))
        shared.append(text)
    return shared


def _read_cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    value_node = cell.find("a:v", NS_MAIN)
    if value_node is None or value_node.text is None:
        return ""

    value = value_node.text
    if cell.attrib.get("t") == "s":
        return shared_strings[int(value)]
    return value


def _sheet_targets(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_root.findall("r:Relationship", NS_REL)
    }

    sheets: list[tuple[str, str]] = []
    sheets_root = workbook.find("a:sheets", NS_MAIN)
    if sheets_root is None:
        return sheets
    for sheet in sheets_root:
        rel_id = sheet.attrib.get(f"{{{WORKBOOK_REL_NS}}}id")
        if not rel_id:
            continue
        target = rel_targets.get(rel_id, "")
        if not target:
            continue
        target_path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        sheets.append((sheet.attrib.get("name", "Sheet"), target_path))
    return sheets


def _read_sheet_rows(archive: ZipFile, sheet_path: str, shared_strings: list[str]) -> list[tuple[int, dict[str, str]]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: list[tuple[int, dict[str, str]]] = []
    sheet_data = root.find("a:sheetData", NS_MAIN)
    if sheet_data is None:
        return rows
    for row in sheet_data:
        values: dict[str, str] = {}
        for cell in row.findall("a:c", NS_MAIN):
            ref = cell.attrib.get("r", "")
            match = re.match(r"[A-Z]+", ref)
            if not match:
                continue
            values[match.group(0)] = _normalize_text(_read_cell_text(cell, shared_strings))
        rows.append((int(row.attrib["r"]), values))
    return rows


def _price_options(raw_price: str | None) -> list[float]:
    if not raw_price:
        return []
    return [float(match) for match in re.findall(r"\d+(?:\.\d+)?", raw_price)]


def _split_variant_letters(value: str) -> list[str]:
    return [char for char in value if char.isalpha()]


def expand_supplier_codes(raw_model: str) -> list[str]:
    raw_model = _normalize_text(raw_model)
    if not raw_model:
        return []

    normalized = raw_model.replace("，", " ").replace(",", " ")
    tokens = [token for token in re.split(r"[/\s]+", normalized) if token]
    if not tokens:
        return []

    single_match = re.fullmatch(r"([A-Za-z]+\d+)([A-Za-z]{2,})", tokens[0])
    if len(tokens) == 1 and single_match:
        stem, variants = single_match.groups()
        return [f"{stem}{variant}" for variant in _split_variant_letters(variants)]

    first_match = re.fullmatch(r"([A-Za-z]+\d+)([A-Za-z]*)", tokens[0])
    if not first_match:
        return [raw_model]

    stem, suffix = first_match.groups()
    remaining = tokens[1:]
    codes: list[str] = []

    if suffix:
        if len(suffix) == 1:
            codes.append(f"{stem}{suffix}")
        else:
            codes.extend(f"{stem}{variant}" for variant in _split_variant_letters(suffix))
    else:
        if not remaining:
            codes.append(stem)
        elif not all(re.fullmatch(r"[A-Za-z]+", token) for token in remaining):
            codes.append(stem)

    for token in remaining:
        if re.fullmatch(r"[A-Za-z]+", token):
            codes.extend(f"{stem}{variant}" for variant in _split_variant_letters(token))
        else:
            token_match = re.fullmatch(r"([A-Za-z]+\d+)([A-Za-z]*)", token)
            if token_match:
                full_stem, full_suffix = token_match.groups()
                if full_suffix:
                    if len(full_suffix) == 1:
                        codes.append(f"{full_stem}{full_suffix}")
                    else:
                        codes.extend(f"{full_stem}{variant}" for variant in _split_variant_letters(full_suffix))
                else:
                    codes.append(full_stem)
            else:
                codes.append(token)

    # Preserve workbook ordering but collapse duplicates.
    unique_codes: list[str] = []
    for code in codes:
        if code not in unique_codes:
            unique_codes.append(code)
    return unique_codes


def _extract_sheet_products(catalog_file: str, sheet_name: str, rows: list[tuple[int, dict[str, str]]]) -> list[dict]:
    sheet_products: list[dict] = []
    start_columns = [1, 4, 7, 10]

    for row_index, (row_number, values) in enumerate(rows):
        for start_column in start_columns:
            label_column = _column_name(start_column)
            value_column = _column_name(start_column + 1)
            if _normalize_label(values.get(label_column)) != "model":
                continue

            raw_model = _normalize_text(values.get(value_column))
            if not raw_model:
                continue

            attributes: dict[str, str] = {}
            for offset in range(6):
                if row_index + offset >= len(rows):
                    continue
                _, attribute_values = rows[row_index + offset]
                label = _normalize_label(attribute_values.get(label_column))
                if not label:
                    continue
                attributes[label] = _normalize_text(attribute_values.get(value_column))

            raw_price = attributes.get("unit price") or attributes.get("special")
            price_label = "unit_price" if attributes.get("unit price") else "special" if attributes.get("special") else None
            expanded_codes = expand_supplier_codes(raw_model)

            sheet_products.append(
                {
                    "catalog_product_id": f"{Path(catalog_file).stem}:{_slugify(sheet_name)}:{row_number}:{label_column}",
                    "catalog_file": catalog_file,
                    "sheet_name": sheet_name,
                    "source_block_row": row_number,
                    "source_value_column": value_column,
                    "raw_model": raw_model,
                    "supplier_item_codes": expanded_codes,
                    "primary_supplier_item_code": expanded_codes[0] if expanded_codes else raw_model,
                    "display_name": attributes.get("name") or None,
                    "size": attributes.get("size") or None,
                    "materials": attributes.get("materials") or None,
                    "color": attributes.get("color") or None,
                    "price_label": price_label,
                    "price_options_cny": _price_options(raw_price),
                    "raw_price": raw_price,
                    "attributes": attributes,
                }
            )

    return sheet_products


def extract_catalog(folder: Path) -> dict:
    profile = _load_json(folder / "supplier_profile.json")
    products: list[dict] = []
    source_files: list[dict] = []

    for source in profile.get("catalog_sources", []):
        file_path = folder / source["file"]
        with ZipFile(file_path) as archive:
            shared_strings = _load_shared_strings(archive)
            sheets = _sheet_targets(archive)
            source_files.append(
                {
                    "file": source["file"],
                    "description": source.get("description"),
                    "sheet_names": [sheet_name for sheet_name, _ in sheets],
                }
            )
            for sheet_name, sheet_path in sheets:
                rows = _read_sheet_rows(archive, sheet_path, shared_strings)
                products.extend(_extract_sheet_products(source["file"], sheet_name, rows))

    code_index: dict[str, int] = {}
    for product in products:
        for code in product["supplier_item_codes"]:
            code_index[code] = code_index.get(code, 0) + 1

    return {
        "schema_version": 1,
        "supplier_id": profile["id"],
        "supplier_name": profile["name"],
        "catalog_sources": source_files,
        "products": products,
        "summary": {
            "catalog_product_count": len(products),
            "distinct_supplier_codes": len(code_index),
            "duplicate_code_count": sum(1 for count in code_index.values() if count > 1),
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: extract_supplier_catalog.py /path/to/docs/suppliers/<supplier>", file=sys.stderr)
        return 2

    folder = Path(argv[1]).resolve()
    output_path = folder / "catalog_products.json"
    data = extract_catalog(folder)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
