#!/usr/bin/env python3
"""
Build Master Product List — merge products from multiple sources into a
unified catalog with channel-ready SKU codes for NEC POS, Amazon, and Google.

Sources:
  1. Stock check OCR output (data/ocr_outputs/stockcheck.json)
  2. Product embedding index (data/catalog/product_embedding_index.json)
  3. Sales taka OCR output (data/ocr_outputs/sales_taka_gcp_vertex.json)

Output:
  data/master_product_list.json — unified product catalog

Usage:
  python build_master_product_list.py
  python build_master_product_list.py --use-gemini  # AI-assisted dedup & categorization
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from identifier_utils import (
    allocate_identifier_pair,
    is_valid_ean13,
    is_valid_plu,
    max_sku_sequence,
    parse_sku_sequence,
    validate_identifier_pair,
)

# ── Defaults ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STOCKCHECK_JSON = "data/ocr_outputs/stockcheck.json"
DEFAULT_EMBEDDING_INDEX = "data/catalog/product_embedding_index.json"
DEFAULT_SALES_TAKA_JSON = "data/ocr_outputs/sales_taka_gcp_vertex.json"
DEFAULT_OUTPUT = "data/master_product_list.json"

# ── Gemini schema for product classification ─────────────────────────────────

CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "products": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "input_name": {"type": "STRING"},
                    "canonical_name": {
                        "type": "STRING",
                        "description": "Cleaned, standardized product name",
                    },
                    "material": {
                        "type": "STRING",
                        "description": "Primary material/gemstone (e.g. Amethyst, Jade, Rose Quartz)",
                    },
                    "product_type": {
                        "type": "STRING",
                        "description": "Product type: Bracelet, Necklace, Ring, Pendant, Earring, Figurine, Sculpture, Home Decor, Bookend, Bowl, Wall Art, Other",
                    },
                    "category": {
                        "type": "STRING",
                        "description": "Category path: Jewellery > Bracelet, Home Decor > Figurine, etc.",
                    },
                    "google_product_category": {
                        "type": "STRING",
                        "description": "Google product taxonomy ID e.g. 'Apparel & Accessories > Jewelry > Bracelets'",
                    },
                },
                "required": ["input_name", "canonical_name", "material", "product_type", "category"],
            },
        },
    },
    "required": ["products"],
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class RawProduct:
    """A product mention from any source."""
    name: str
    name_raw: str = ""
    code: str = ""
    source: str = ""
    quantity: int | None = None
    unit_price: float | None = None
    total_price: float | None = None
    material: str = ""
    product_type: str = ""


@dataclass
class MasterProduct:
    """Unified product entry for the master list."""
    id: str = ""
    internal_code: str = ""
    sku_code: str = ""
    description: str = ""
    long_description: str = ""
    material: str = ""
    product_type: str = ""
    category: str = ""
    amazon_sku: str = ""
    google_product_id: str = ""
    google_product_category: str = ""
    nec_plu: str = ""
    cost_price: float | None = None
    retail_price: float | None = None
    qty_on_hand: int | None = None
    sources: list[str] = field(default_factory=list)
    raw_names: list[str] = field(default_factory=list)
    mention_count: int = 0
    # ── Director-level inventory classification ──
    inventory_type: str = ""          # finished | material | purchased (aligns with backend InventoryType)
    sourcing_strategy: str = ""       # supplier_premade | manufactured_standard | manufactured_custom
    inventory_category: str = ""      # Director-level bucket: finished_for_sale, catalog_to_stock, material, store_operations
    sale_ready: bool = False           # True = can go on NEC POS right now
    block_sales: bool = False          # True = not for sale (materials, ops items)
    stocking_status: str = ""         # in_stock, to_order, to_manufacture, not_stocked
    stocking_location: str = ""       # default location hint: takashimaya_counter, warehouse
    use_stock: bool = True


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Normalize text for deduplication matching."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_material(text: str) -> str:
    """Extract primary material/gemstone from product name."""
    materials = [
        "amethyst", "jade", "rose quartz", "quartz", "tourmaline", "agate",
        "malachite", "lapis lazuli", "lapis", "obsidian", "citrine", "garnet",
        "moonstone", "opal", "pearl", "ruby", "sapphire", "emerald", "topaz",
        "turquoise", "aquamarine", "carnelian", "onyx", "tiger eye", "jasper",
        "fluorite", "labradorite", "peridot", "alexandrite", "tanzanite",
        "iolite", "kunzite", "morganite", "rhodochrosite", "sugilite",
        "chrysoprase", "howlite", "sodalite", "larimar", "sunstone",
        "diopside", "crystal", "marble", "stone", "rattan", "copper",
        "glass", "brass", "metal", "silver", "gold", "ametrine",
        "watermelon tourmaline", "black tourmaline", "smoky quartz",
        "strawberry quartz", "phantom quartz", "rutilated quartz",
        "imperial diopside",
    ]
    text_lower = text.lower()
    # Try longest match first
    materials.sort(key=len, reverse=True)
    for mat in materials:
        if mat in text_lower:
            return mat.title()
    return ""


# Canonical product types — every product must map to one of these.
ALL_PRODUCT_TYPES = [
    "Bracelet", "Necklace", "Ring", "Pendant", "Earring",
    "Figurine", "Sculpture", "Bookend", "Bowl", "Wall Art",
    "Vase", "Tray", "Box", "Candle Holder", "Lamp", "Clock",
    "Mirror", "Coaster",
    # Gemstone / material forms
    "Loose Gemstone", "Tumbled Stone", "Raw Specimen", "Crystal Cluster",
    "Gemstone Bead", "Cabochon",
    # Jewellery-making supplies
    "Bead Strand", "Charm", "Jewellery Component",
    # Home / display
    "Decorative Object", "Healing Crystal", "Crystal Point",
    # Service / misc
    "Gift Set", "Repair Service", "Accessory",
]


def extract_product_type(text: str) -> str:
    """Extract product type from description."""
    type_map = {
        "bracelet": "Bracelet",
        "necklace": "Necklace",
        "ring": "Ring",
        "pendant": "Pendant",
        "earring": "Earring",
        "figurine": "Figurine",
        "sculpture": "Sculpture",
        "bookend": "Bookend",
        "bowl": "Bowl",
        "wall decor": "Wall Art",
        "wall art": "Wall Art",
        "vase": "Vase",
        "tray": "Tray",
        "box": "Box",
        "candle holder": "Candle Holder",
        "lamp": "Lamp",
        "clock": "Clock",
        "mirror": "Mirror",
        "coaster": "Coaster",
        # New expanded types
        "loose": "Loose Gemstone",
        "tumbled": "Tumbled Stone",
        "raw": "Raw Specimen",
        "specimen": "Raw Specimen",
        "cluster": "Crystal Cluster",
        "geode": "Crystal Cluster",
        "bead": "Gemstone Bead",
        "cabochon": "Cabochon",
        "strand": "Bead Strand",
        "charm": "Charm",
        "component": "Jewellery Component",
        "finding": "Jewellery Component",
        "decorative": "Decorative Object",
        "decor": "Decorative Object",
        "healing": "Healing Crystal",
        "point": "Crystal Point",
        "tower": "Crystal Point",
        "wand": "Crystal Point",
        "gift set": "Gift Set",
        "repair": "Repair Service",
        "restring": "Repair Service",
    }
    text_lower = text.lower()
    for key, value in type_map.items():
        if key in text_lower:
            return value
    return "Loose Gemstone"


def generate_sku_code(internal_code: str, material: str, product_type: str, seq: int) -> str:
    """Generate a 16-char NEC-compatible SKU code.

    Format: VE{TYPE}{MATL}{SEQ}
    Example: VEBRAQTZ00000001 (Bracelet, Quartz, #1)
    """
    type_abbr = {
        "Bracelet": "BRA", "Necklace": "NEC", "Ring": "RNG", "Pendant": "PEN",
        "Earring": "EAR", "Figurine": "FIG", "Sculpture": "SCU", "Bookend": "BKE",
        "Bowl": "BWL", "Wall Art": "WAL", "Vase": "VAS", "Tray": "TRY",
        "Box": "BOX", "Candle Holder": "CAN", "Lamp": "LMP", "Clock": "CLK",
        "Mirror": "MIR", "Coaster": "CST",
        "Loose Gemstone": "LGM", "Tumbled Stone": "TUM", "Raw Specimen": "RAW",
        "Crystal Cluster": "CLU", "Gemstone Bead": "GBD", "Cabochon": "CAB",
        "Bead Strand": "BST", "Charm": "CHM", "Jewellery Component": "JWC",
        "Decorative Object": "DEC", "Healing Crystal": "HCR", "Crystal Point": "CPT",
        "Gift Set": "GFT", "Repair Service": "SVC", "Accessory": "ACC",
    }.get(product_type, "LGM")

    mat_abbr = re.sub(r"[^A-Z]", "", material.upper()[:4]).ljust(4, "X")[:4]
    return f"VE{type_abbr}{mat_abbr}{seq:07d}"


def generate_amazon_sku(internal_code: str, material: str, product_type: str) -> str:
    """Generate an Amazon-friendly SKU.

    Format: VE-{MATERIAL}-{TYPE}-{CODE}
    """
    mat = re.sub(r"[^A-Z0-9]", "", material.upper()[:12])
    typ = re.sub(r"[^A-Z0-9]", "", product_type.upper()[:4])
    code = internal_code.upper() if internal_code else "NOCODE"
    return f"VE-{mat}-{typ}-{code}"


def generate_google_product_id(sku_code: str) -> str:
    """Generate Google Merchant Center product ID."""
    return f"online:en:SG:{sku_code}"


def generate_nec_plu(seq: int) -> str:
    from identifier_utils import generate_nec_plu as _generate_nec_plu

    return _generate_nec_plu(seq)


# ── Source loaders ────────────────────────────────────────────────────────────

def load_stockcheck_products(path: Path) -> list[RawProduct]:
    """Load products from stock check OCR output."""
    if not path.exists():
        print(f"  (skipping {path} — not found)")
        return []

    data = json.loads(path.read_text())
    products: list[RawProduct] = []
    for page in data.get("pages", []):
        for item in page.get("items", []):
            name = item.get("product_name", "") or ""
            if not name.strip():
                continue
            products.append(RawProduct(
                name=name,
                name_raw=item.get("product_name_raw", name),
                code=item.get("product_code", "") or "",
                source="stockcheck",
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                total_price=item.get("total_price"),
            ))
    print(f"  Stock check: {len(products)} products")
    return products


def load_embedding_products(path: Path) -> list[RawProduct]:
    """Load products from product embedding index."""
    if not path.exists():
        print(f"  (skipping {path} — not found)")
        return []

    data = json.loads(path.read_text())
    products: list[RawProduct] = []
    for item in data:
        code = item.get("code", "")
        text = item.get("text", "")
        if text.startswith("None made of None"):
            continue
        products.append(RawProduct(
            name=text.split(".")[0] if text else code,  # First sentence
            name_raw=text,
            code=code,
            source="catalog_embeddings",
        ))
    print(f"  Catalog embeddings: {len(products)} products")
    return products


def load_sales_taka_products(path: Path) -> list[RawProduct]:
    """Load unique product descriptions from sales taka OCR."""
    if not path.exists():
        print(f"  (skipping {path} — not found)")
        return []

    data = json.loads(path.read_text())
    seen: dict[str, int] = {}
    products: list[RawProduct] = []
    for doc in data.get("documents", []):
        for page in doc.get("pages", []):
            for entry in page.get("entries", []):
                for item in entry.get("items", []):
                    desc = item.get("description_raw", "") or ""
                    if not desc.strip() or len(desc.strip()) < 3:
                        continue
                    norm = normalize_text(desc)
                    if norm in seen:
                        seen[norm] += 1
                        continue
                    seen[norm] = 1
                    amt = item.get("amount")
                    products.append(RawProduct(
                        name=desc.strip(),
                        name_raw=desc,
                        source="sales_taka",
                        unit_price=float(amt) if amt else None,
                    ))
    print(f"  Sales taka: {len(products)} unique products (from {sum(seen.values())} mentions)")
    return products


# ── Deduplication ─────────────────────────────────────────────────────────────

def load_existing_identifier_assignments(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    assignments: dict[str, dict[str, str]] = {}
    for product in data.get("products", []):
        product_id = str(product.get("id") or "").strip()
        sku_code = str(product.get("sku_code") or "").strip()
        nec_plu = str(product.get("nec_plu") or "").strip()
        if not product_id or not sku_code or not nec_plu:
            continue
        assignments[product_id] = {"sku_code": sku_code, "nec_plu": nec_plu}
    return assignments


def _reuse_or_allocate_identifiers(
    product_id: str,
    *,
    sku_factory: Any,
    existing_assignments: dict[str, dict[str, str]],
    used_sku_codes: set[str],
    used_plus: set[str],
    next_seq: int,
) -> tuple[str, str, int]:
    assignment = existing_assignments.get(product_id)
    if assignment:
        sku_code = assignment.get("sku_code", "").strip()
        nec_plu = assignment.get("nec_plu", "").strip()
        # Honour either the new EAN-8 codes or the legacy 13-digit codes —
        # the rebuilder isn't responsible for migrating between encodings,
        # only for not breaking callers who feed it cached assignments.
        if (
            sku_code
            and nec_plu
            and sku_code not in used_sku_codes
            and nec_plu not in used_plus
            and (is_valid_plu(nec_plu) or is_valid_ean13(nec_plu))
        ):
            validate_identifier_pair(sku_code, nec_plu)
            used_sku_codes.add(sku_code)
            used_plus.add(nec_plu)
            seq = parse_sku_sequence(sku_code) or 0
            return sku_code, nec_plu, max(next_seq, seq + 1)

    return allocate_identifier_pair(sku_factory, used_sku_codes, used_plus, next_seq)


def deduplicate_products(
    all_products: list[RawProduct],
    existing_assignments: dict[str, dict[str, str]] | None = None,
) -> list[MasterProduct]:
    """Group raw products into deduplicated master products.

    Strategy:
    1. Group by internal code (exact match)
    2. Group remaining by normalized name similarity
    3. Merge groups into MasterProduct entries
    """
    # Phase 1: group by code
    code_groups: dict[str, list[RawProduct]] = defaultdict(list)
    no_code: list[RawProduct] = []

    for p in all_products:
        if p.code and p.code.strip():
            code_groups[p.code.strip().upper()].append(p)
        else:
            no_code.append(p)

    # Phase 2: group no-code products by normalized name
    name_groups: dict[str, list[RawProduct]] = defaultdict(list)
    for p in no_code:
        norm = normalize_text(p.name)
        if len(norm) < 3:
            continue
        # Try to find an existing group with similar name
        matched = False
        for key in list(name_groups.keys()):
            if norm == key or (len(norm) > 5 and norm in key) or (len(key) > 5 and key in norm):
                name_groups[key].append(p)
                matched = True
                break
        if not matched:
            name_groups[norm].append(p)

    # Phase 3: merge into MasterProduct list
    masters: list[MasterProduct] = []
    existing_assignments = existing_assignments or {}
    used_sku_codes: set[str] = set()
    used_plus: set[str] = set()
    seq = max_sku_sequence(
        assignment.get("sku_code") for assignment in existing_assignments.values()
    ) + 1
    seq = max(seq, 1)

    # Process code-based groups first
    for code, group in sorted(code_groups.items()):
        best = max(group, key=lambda p: len(p.name))
        material = extract_material(best.name) or extract_material(best.name_raw)
        ptype = extract_product_type(best.name) or extract_product_type(best.name_raw)

        # Get quantity from stockcheck source if available
        qty = None
        cost = None
        retail = None
        for p in group:
            if p.source == "stockcheck" and p.quantity is not None:
                qty = (qty or 0) + p.quantity
            if p.unit_price and not cost:
                cost = p.unit_price
            if p.total_price and not retail:
                retail = p.total_price

        product_id = hashlib.md5(code.encode()).hexdigest()[:12]
        mp = MasterProduct(
            id=product_id,
            internal_code=code,
            description=best.name[:60],
            long_description=best.name_raw[:1000] if best.name_raw else best.name,
            material=material,
            product_type=ptype,
            category=ptype,
            cost_price=cost,
            retail_price=retail,
            qty_on_hand=qty,
            sources=list({p.source for p in group}),
            raw_names=list({p.name for p in group}),
            mention_count=len(group),
        )
        mp.sku_code, mp.nec_plu, seq = _reuse_or_allocate_identifiers(
            product_id,
            sku_factory=lambda seq_num, code=code, material=material, ptype=ptype: generate_sku_code(code, material, ptype, seq_num),
            existing_assignments=existing_assignments,
            used_sku_codes=used_sku_codes,
            used_plus=used_plus,
            next_seq=seq,
        )
        mp.amazon_sku = generate_amazon_sku(code, material, ptype)
        mp.google_product_id = generate_google_product_id(mp.sku_code)
        masters.append(mp)

    # Process name-based groups
    for norm_name, group in sorted(name_groups.items()):
        best = max(group, key=lambda p: len(p.name))
        material = extract_material(best.name) or extract_material(best.name_raw)
        ptype = extract_product_type(best.name) or extract_product_type(best.name_raw)

        qty = None
        cost = None
        for p in group:
            if p.source == "stockcheck" and p.quantity is not None:
                qty = (qty or 0) + p.quantity
            if p.unit_price and not cost:
                cost = p.unit_price

        # Generate a short code from hash if none available
        short_code = hashlib.md5(norm_name.encode()).hexdigest()[:6].upper()

        product_id = hashlib.md5(norm_name.encode()).hexdigest()[:12]
        mp = MasterProduct(
            id=product_id,
            internal_code="",
            description=best.name[:60],
            long_description=best.name_raw[:1000] if best.name_raw else best.name,
            material=material,
            product_type=ptype,
            category=ptype,
            cost_price=cost,
            qty_on_hand=qty,
            sources=list({p.source for p in group}),
            raw_names=list({p.name for p in group}),
            mention_count=len(group),
        )
        mp.sku_code, mp.nec_plu, seq = _reuse_or_allocate_identifiers(
            product_id,
            sku_factory=lambda seq_num, short_code=short_code, material=material, ptype=ptype: generate_sku_code(short_code, material, ptype, seq_num),
            existing_assignments=existing_assignments,
            used_sku_codes=used_sku_codes,
            used_plus=used_plus,
            next_seq=seq,
        )
        mp.amazon_sku = generate_amazon_sku(short_code, material, ptype)
        mp.google_product_id = generate_google_product_id(mp.sku_code)
        masters.append(mp)

    return masters


# ── Gemini-assisted classification (optional) ─────────────────────────────────

def classify_with_gemini(
    products: list[MasterProduct],
    project_id: str,
    location: str,
    model: str,
    batch_size: int = 15,
) -> list[MasterProduct]:
    """Use Gemini to clean up and standardize product names and categories."""
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project_id, location=location)

    # Process in batches to avoid token limits
    for batch_start in range(0, len(products), batch_size):
        batch = products[batch_start:batch_start + batch_size]
        names = [p.description for p in batch]

        types_str = ", ".join(ALL_PRODUCT_TYPES)
        prompt = (
            "Classify these retail products. They are luxury crystal/gemstone "
            "jewellery and home decor items sold at a Takashimaya department store.\n\n"
            "For each product, provide:\n"
            "- canonical_name: cleaned, standardized name\n"
            "- material: primary gemstone/material\n"
            f"- product_type: MUST be exactly one of: {types_str}\n"
            "  NEVER use 'Other'. Pick the closest match from the list above.\n"
            "  If the item is a loose/raw/unset gemstone, use 'Loose Gemstone'.\n"
            "  If it is a tumbled/polished stone, use 'Tumbled Stone'.\n"
            "  If it is a rough/raw specimen, use 'Raw Specimen'.\n"
            "  If it is a cluster or geode, use 'Crystal Cluster'.\n"
            "  If it is beads or a strand, use 'Gemstone Bead' or 'Bead Strand'.\n"
            "  If it is a decorative/display item, use 'Decorative Object'.\n"
            "  If it is a crystal point/tower/wand, use 'Crystal Point'.\n"
            "- category: hierarchical path (e.g. 'Jewellery > Bracelet > Crystal')\n"
            "- google_product_category: Google taxonomy path\n\n"
            "Products:\n" + "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
        )

        try:
            def _timeout_handler(signum: int, frame: Any) -> None:
                raise TimeoutError("Gemini classification timed out")

            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(120)
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=CLASSIFY_SCHEMA,
                        temperature=0.1,
                        max_output_tokens=16384,
                    ),
                )
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            if response.text:
                raw = response.text.strip()
                # Attempt to repair truncated JSON
                if not raw.endswith("}"):
                    # Find last complete object
                    last_brace = raw.rfind("}")
                    if last_brace > 0:
                        raw = raw[:last_brace + 1]
                        # Ensure arrays and outer object are closed
                        open_brackets = raw.count("[") - raw.count("]")
                        open_braces = raw.count("{") - raw.count("}")
                        raw += "]" * max(0, open_brackets)
                        raw += "}" * max(0, open_braces)
                result = json.loads(raw)
                classified = result.get("products", [])
                for i, cp in enumerate(classified):
                    if i < len(batch):
                        if cp.get("canonical_name"):
                            batch[i].description = cp["canonical_name"][:60]
                        if cp.get("material"):
                            batch[i].material = cp["material"]
                        if cp.get("product_type"):
                            batch[i].product_type = cp["product_type"]
                        if cp.get("category"):
                            batch[i].category = cp["category"]
                        if cp.get("google_product_category"):
                            batch[i].google_product_category = cp["google_product_category"]
                            # Regenerate SKU codes with updated info
                            batch[i].amazon_sku = generate_amazon_sku(
                                batch[i].internal_code, batch[i].material, batch[i].product_type
                            )

                print(f"    Classified batch {batch_start+1}-{batch_start+len(batch)}: "
                      f"{len(classified)} products")
        except Exception as exc:
            print(f"    WARNING: Gemini classification failed for batch: {exc}")

        # Respect rate limits
        time.sleep(2)

    # Post-classification: force zero "Other" — remap to closest valid type
    valid_set = set(ALL_PRODUCT_TYPES)
    remapped = 0
    for p in products:
        if p.product_type not in valid_set:
            p.product_type = "Loose Gemstone"
            p.category = p.category if p.category and "Other" not in p.category else "Gemstones > Loose Gemstone"
            remapped += 1
    if remapped:
        print(f"    Post-Gemini: remapped {remapped} invalid product_types → valid types")

    return products


# ── Director-level inventory classification ──────────────────────────────────

# Product types that are finished goods ready for NEC POS
_FINISHED_TYPES = {
    "Bracelet", "Necklace", "Ring", "Pendant", "Earring",
    "Figurine", "Sculpture", "Bookend", "Bowl", "Wall Art",
    "Vase", "Tray", "Box", "Candle Holder", "Lamp", "Clock",
    "Mirror", "Coaster", "Decorative Object", "Healing Crystal",
    "Crystal Point", "Crystal Cluster", "Charm",
}
# Catalog items: can be purchased/stocked but aren't finished goods yet
_CATALOG_TYPES = {"Loose Gemstone", "Tumbled Stone", "Cabochon"}
# Materials used to manufacture finished items
_MATERIAL_TYPES = {"Raw Specimen", "Gemstone Bead", "Bead Strand", "Jewellery Component"}
# Store operations: services, packaging, stationery
_OPS_TYPES = {"Repair Service", "Gift Set", "Accessory"}

# Types that imply the item was manufactured in-house (subset of finished)
_MANUFACTURED_HINTS = {"bracelet", "necklace", "ring", "pendant", "earring", "charm"}


def classify_inventory_fields(p: MasterProduct) -> None:
    """Assign director-level inventory fields based on product_type and sources."""
    pt = p.product_type
    desc_lower = p.description.lower()
    has_stock = p.qty_on_hand is not None and p.qty_on_hand > 0
    has_code = bool(p.internal_code)
    from_stockcheck = "stockcheck" in p.sources

    # ── inventory_category (director-level bucket) ──
    if pt in _OPS_TYPES:
        p.inventory_category = "store_operations"
        p.inventory_type = "finished"
        p.sourcing_strategy = "supplier_premade"
        p.sale_ready = pt == "Gift Set"
        p.block_sales = pt != "Gift Set"
        p.stocking_status = "in_stock" if has_stock else "to_order"
        p.stocking_location = "takashimaya_counter"
        p.use_stock = pt == "Gift Set"

    elif pt in _MATERIAL_TYPES:
        p.inventory_category = "material"
        p.inventory_type = "material"
        p.sourcing_strategy = "supplier_premade"
        p.sale_ready = False
        p.block_sales = True
        p.stocking_status = "in_stock" if has_stock else "to_order"
        # Workshop is not a standalone location anymore; materials roll up into warehouse.
        p.stocking_location = "warehouse"
        p.use_stock = True

    elif pt in _CATALOG_TYPES:
        p.inventory_category = "catalog_to_stock"
        p.inventory_type = "purchased"
        p.sourcing_strategy = "supplier_premade"
        # Catalog items with stock or internal codes are sale-ready
        p.sale_ready = has_stock or has_code or from_stockcheck
        p.block_sales = False
        if has_stock or from_stockcheck:
            p.stocking_status = "in_stock"
            p.stocking_location = "takashimaya_counter"
        elif has_code:
            p.stocking_status = "to_order"
            p.stocking_location = "warehouse"
        else:
            p.stocking_status = "not_stocked"
            p.stocking_location = ""
        p.use_stock = True

    elif pt in _FINISHED_TYPES:
        p.inventory_category = "finished_for_sale"
        p.inventory_type = "finished"
        # Detect manufactured vs supplier premade
        is_manufactured = (
            any(h in desc_lower for h in _MANUFACTURED_HINTS)
            and "stockcheck" in p.sources
        )
        p.sourcing_strategy = "manufactured_standard" if is_manufactured else "supplier_premade"
        p.sale_ready = True
        p.block_sales = False
        p.stocking_status = "in_stock" if has_stock else "to_order"
        p.stocking_location = "takashimaya_counter"
        p.use_stock = True

    else:
        # Fallback: treat as catalog
        p.inventory_category = "catalog_to_stock"
        p.inventory_type = "purchased"
        p.sourcing_strategy = "supplier_premade"
        p.sale_ready = False
        p.block_sales = False
        p.stocking_status = "not_stocked"
        p.stocking_location = ""
        p.use_stock = True


def assign_inventory_classification(products: list[MasterProduct]) -> list[MasterProduct]:
    """Classify all products with director-level inventory fields."""
    for p in products:
        classify_inventory_fields(p)
    return products


def validate_master_identifiers(products: list[MasterProduct]) -> None:
    seen_sku_codes: set[str] = set()
    seen_plus: set[str] = set()
    for product in products:
        validate_identifier_pair(product.sku_code, product.nec_plu)
        if product.sku_code in seen_sku_codes:
            raise ValueError(f"Duplicate sku_code generated: {product.sku_code}")
        if product.nec_plu in seen_plus:
            raise ValueError(f"Duplicate nec_plu generated: {product.nec_plu}")
        seen_sku_codes.add(product.sku_code)
        seen_plus.add(product.nec_plu)


# ── Location-level SKU lists ─────────────────────────────────────────────────

DEFAULT_LOCATIONS = {
    "takashimaya_counter": {
        "name": "Takashimaya Counter",
        "store_id_hint": "taka-main",
        "description": "Main retail counter at Takashimaya department store",
    },
    "warehouse": {
        "name": "Warehouse / Back-of-House",
        "store_id_hint": "warehouse-01",
        "description": "Warehouse storage for unallocated, incoming, and material stock",
    },
}


def write_location_lists(base_dir: Path, products: list[MasterProduct]) -> None:
    """Generate per-location SKU lists from the director-level master list."""
    base_dir.mkdir(parents=True, exist_ok=True)

    # Group products by stocking_location
    loc_map: dict[str, list[MasterProduct]] = {}
    for p in products:
        loc = p.stocking_location or "unassigned"
        loc_map.setdefault(loc, []).append(p)

    for loc_key, items in sorted(loc_map.items()):
        loc_meta = DEFAULT_LOCATIONS.get(loc_key, {"name": loc_key, "store_id_hint": loc_key, "description": ""})
        items.sort(key=lambda p: (p.inventory_category, p.product_type, p.description))

        loc_output = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "location": loc_meta,
            "total_skus": len(items),
            "summary": {
                "sale_ready": sum(1 for p in items if p.sale_ready),
                "blocked": sum(1 for p in items if p.block_sales),
                "in_stock": sum(1 for p in items if p.stocking_status == "in_stock"),
                "to_order": sum(1 for p in items if p.stocking_status == "to_order"),
                "by_inventory_category": dict(Counter(p.inventory_category for p in items).most_common()),
                "by_type": dict(Counter(p.product_type for p in items).most_common()),
            },
            "skus": [
                {
                    "sku_code": p.sku_code,
                    "nec_plu": p.nec_plu,
                    "description": p.description,
                    "material": p.material,
                    "product_type": p.product_type,
                    "inventory_type": p.inventory_type,
                    "sourcing_strategy": p.sourcing_strategy,
                    "inventory_category": p.inventory_category,
                    "sale_ready": p.sale_ready,
                    "block_sales": p.block_sales,
                    "use_stock": p.use_stock,
                    "cost_price": p.cost_price,
                    "qty_on_hand": p.qty_on_hand,
                    "internal_code": p.internal_code,
                    "amazon_sku": p.amazon_sku,
                    "google_product_id": p.google_product_id,
                }
                for p in items
            ],
        }
        fname = f"location_skus_{loc_key}.json"
        out_path = base_dir / fname
        out_path.write_text(json.dumps(loc_output, indent=2, ensure_ascii=False, default=str))
        print(f"  Location list: {out_path.name:40s}  {len(items):4d} SKUs  "
              f"({sum(1 for p in items if p.sale_ready)} sale-ready)")


# ── Output ────────────────────────────────────────────────────────────────────

def write_master_list(path: Path, products: list[MasterProduct]) -> None:
    """Write the master product list as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # Sort: coded products first, then by material/type
    products.sort(key=lambda p: (
        0 if p.internal_code else 1,
        p.material or "zzz",
        p.product_type or "zzz",
        p.description,
    ))

    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_products": len(products),
        "summary": {
            "with_internal_code": sum(1 for p in products if p.internal_code),
            "with_quantity": sum(1 for p in products if p.qty_on_hand is not None),
            "with_price": sum(1 for p in products if p.cost_price is not None),
            "sale_ready": sum(1 for p in products if p.sale_ready),
            "blocked": sum(1 for p in products if p.block_sales),
            "by_type": dict(Counter(p.product_type for p in products).most_common()),
            "by_material": dict(Counter(p.material for p in products if p.material).most_common(20)),
            "by_source": dict(Counter(s for p in products for s in p.sources).most_common()),
            "by_inventory_category": dict(Counter(p.inventory_category for p in products).most_common()),
            "by_stocking_status": dict(Counter(p.stocking_status for p in products).most_common()),
            "by_stocking_location": dict(Counter(p.stocking_location or "unassigned" for p in products).most_common()),
        },
        "products": [asdict(p) for p in products],
    }
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))


def print_summary(products: list[MasterProduct]) -> None:
    """Print a summary of the master product list."""
    print(f"\n{'='*60}")
    print(f"MASTER PRODUCT LIST")
    print(f"{'='*60}")
    print(f"Total products: {len(products)}")
    print(f"  With internal code: {sum(1 for p in products if p.internal_code)}")
    print(f"  With quantity:      {sum(1 for p in products if p.qty_on_hand is not None)}")
    print(f"  With cost price:    {sum(1 for p in products if p.cost_price is not None)}")
    print()

    # Director-level inventory summary
    print("Director-Level Inventory:")
    cat_counts = Counter(p.inventory_category for p in products)
    for cat, count in cat_counts.most_common():
        ready = sum(1 for p in products if p.inventory_category == cat and p.sale_ready)
        print(f"  {cat:25s} {count:4d}  ({ready} sale-ready)")
    print(f"  {'TOTAL':25s} {len(products):4d}  "
          f"({sum(1 for p in products if p.sale_ready)} sale-ready, "
          f"{sum(1 for p in products if p.block_sales)} blocked)")
    print()

    stock_counts = Counter(p.stocking_status for p in products)
    print("Stocking status:")
    for status, count in stock_counts.most_common():
        print(f"  {status:25s} {count:4d}")

    loc_counts = Counter(p.stocking_location or 'unassigned' for p in products)
    print("\nStocking location:")
    for loc, count in loc_counts.most_common():
        print(f"  {loc:25s} {count:4d}")
    print()

    type_counts = Counter(p.product_type for p in products)
    print("By product type:")
    for ptype, count in type_counts.most_common(10):
        print(f"  {ptype:20s} {count:4d}")

    mat_counts = Counter(p.material for p in products if p.material)
    print(f"\nTop materials ({len(mat_counts)} total):")
    for mat, count in mat_counts.most_common(15):
        print(f"  {mat:20s} {count:4d}")

    source_counts = Counter(s for p in products for s in p.sources)
    print("\nBy source:")
    for src, count in source_counts.most_common():
        print(f"  {src:25s} {count:4d}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build Master Product List")
    parser.add_argument("--stockcheck-json", default=DEFAULT_STOCKCHECK_JSON)
    parser.add_argument("--embedding-index", default=DEFAULT_EMBEDDING_INDEX)
    parser.add_argument("--sales-taka-json", default=DEFAULT_SALES_TAKA_JSON)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--use-gemini",
        action="store_true",
        help="Use Gemini to improve product classification",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", ""),
    )
    parser.add_argument("--vertex-location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    parser.add_argument("--model", default=os.environ.get("VERTEX_GEMINI_MODEL", "gemini-2.5-flash"))
    args = parser.parse_args()

    repo_root = REPO_ROOT

    def _repo_path(p: str | Path) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()

    output_path = _repo_path(args.output)
    existing_assignments = load_existing_identifier_assignments(output_path)
    if existing_assignments:
        print(f"Loaded {len(existing_assignments)} existing identifier assignments from {output_path.name}")

    print("Loading product sources...")
    all_products: list[RawProduct] = []
    all_products.extend(load_stockcheck_products(_repo_path(args.stockcheck_json)))
    all_products.extend(load_embedding_products(_repo_path(args.embedding_index)))
    all_products.extend(load_sales_taka_products(_repo_path(args.sales_taka_json)))

    print(f"\nTotal raw product mentions: {len(all_products)}")
    print("Deduplicating...")
    masters = deduplicate_products(all_products, existing_assignments=existing_assignments)
    print(f"Deduplicated to {len(masters)} unique products")

    if args.use_gemini and args.project_id:
        print("\nClassifying with Gemini...")
        masters = classify_with_gemini(
            masters,
            project_id=args.project_id,
            location=args.vertex_location,
            model=args.model,
        )

    print("\nAssigning inventory classification...")
    masters = assign_inventory_classification(masters)
    validate_master_identifiers(masters)

    write_master_list(output_path, masters)
    print_summary(masters)
    print(f"\nOutput: {output_path}")

    # Generate location-level SKU lists
    loc_dir = output_path.parent / "location_sku_lists"
    print(f"\nGenerating location-level SKU lists...")
    write_location_lists(loc_dir, masters)
    print(f"Location lists: {loc_dir}")


if __name__ == "__main__":
    main()
