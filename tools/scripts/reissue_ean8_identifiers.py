#!/usr/bin/env python3
"""Bulk wipe-and-reissue every SKU code + EAN-8 PLU on the master JSON.

This is the migration tool for the EAN-13 → EAN-8 switch. It rewrites
``data/master_product_list.json`` in-place: every product gets a fresh
``sku_code`` and ``nec_plu`` aligned to a brand-new sequence number that
restarts at 1.

Pinning
=======
The user has 13 physical Hengwei homeware labels already on the shop floor
labelled #1–#13. Pass ``--pin-file pins.csv`` to claim those sequences for
specific products before the auto-allocator runs:

    match_field,match_value,seq
    internal_code,H001,1
    internal_code,H002,2
    sku_code,VEBWLAMET0000062,3

Pinned products are placed at their reserved seq first; everything else
gets the next free seq (1 onward, skipping pinned seqs) in the order it
appears in the master JSON. Re-running with the same pin file is
deterministic.

Safety
======
- Dry-run by default. Always writes a diff CSV (`data/exports/...`)
  showing every old → new identifier swap so the operator can review
  before applying.
- ``--apply`` writes a timestamped backup of master_product_list.json
  next to the original, then overwrites the file in place.
- Out of scope (deferred): mirroring the new identifiers to Postgres
  (`skus`, `plus`) and Firestore (`skus`, `plus`, `prices`,
  `stores/*/inventory`). Use the existing sync tooling
  (`tools/scripts/sync_master_to_firestore.py`,
  `tools/scripts/repair_invalid_plus_codes.py`) after this lands.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Make sibling helpers importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_master_product_list import (  # noqa: E402  (sys.path tweak above)
    generate_google_product_id,
    generate_sku_code,
)
from identifier_utils import generate_nec_plu  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER = REPO_ROOT / "data" / "master_product_list.json"
DEFAULT_DIFF_DIR = REPO_ROOT / "data" / "exports"

# EAN-8 with prefix "2" + 6 seq digits + check supports 1..999_999. The SKU
# code carries 7 seq digits so it can outgrow that, but for now the EAN-8
# check is the binding constraint — pin against it to fail fast.
MAX_SEQ = 999_999


# ── Data shapes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pin:
    """A single 'pin this product to seq N' rule from the pin file."""

    match_field: str  # one of: "internal_code", "sku_code"
    match_value: str
    seq: int


@dataclass
class PlanRow:
    """One row of the reissuance plan — what a product will look like after."""

    index: int  # position in master JSON; stable ordering key
    product: dict
    new_seq: int
    new_sku_code: str
    new_nec_plu: str
    pinned: bool

    @property
    def old_sku_code(self) -> str:
        return str(self.product.get("sku_code") or "")

    @property
    def old_nec_plu(self) -> str:
        return str(self.product.get("nec_plu") or "")


# ── Pin loading + validation ─────────────────────────────────────────────────


_VALID_MATCH_FIELDS = ("internal_code", "sku_code")


def load_pins(pin_file: Path | None) -> list[Pin]:
    if not pin_file:
        return []
    if not pin_file.exists():
        raise SystemExit(f"Pin file not found: {pin_file}")
    pins: list[Pin] = []
    with pin_file.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"match_field", "match_value", "seq"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise SystemExit(
                f"Pin CSV must have columns {sorted(required)}; "
                f"got {reader.fieldnames}"
            )
        for line_no, row in enumerate(reader, start=2):
            match_field = (row.get("match_field") or "").strip()
            match_value = (row.get("match_value") or "").strip()
            seq_raw = (row.get("seq") or "").strip()
            if match_field not in _VALID_MATCH_FIELDS:
                raise SystemExit(
                    f"Pin CSV line {line_no}: match_field must be one of "
                    f"{_VALID_MATCH_FIELDS}, got {match_field!r}"
                )
            if not match_value:
                raise SystemExit(f"Pin CSV line {line_no}: match_value is empty")
            try:
                seq = int(seq_raw)
            except ValueError:
                raise SystemExit(
                    f"Pin CSV line {line_no}: seq {seq_raw!r} is not an integer"
                )
            if not 1 <= seq <= MAX_SEQ:
                raise SystemExit(
                    f"Pin CSV line {line_no}: seq {seq} out of range [1, {MAX_SEQ}]"
                )
            pins.append(Pin(match_field=match_field, match_value=match_value, seq=seq))
    return pins


def resolve_pins(
    pins: Iterable[Pin],
    products: list[dict],
) -> dict[int, int]:
    """Resolve pins to a {product_index: seq} map.

    Fails loudly on:
    - a pin that matches zero products (typo in the pin file)
    - a pin that matches more than one product (ambiguous match_field)
    - two pins claiming the same seq
    - two pins both claiming the same product
    """
    by_index: dict[int, int] = {}
    seqs_seen: dict[int, Pin] = {}
    pins_list = list(pins)
    for pin in pins_list:
        if pin.seq in seqs_seen:
            existing = seqs_seen[pin.seq]
            raise SystemExit(
                f"Two pins both claim seq={pin.seq}: "
                f"({existing.match_field}={existing.match_value!r}) "
                f"and ({pin.match_field}={pin.match_value!r})"
            )
        seqs_seen[pin.seq] = pin
        matches = [
            i
            for i, p in enumerate(products)
            if str(p.get(pin.match_field) or "") == pin.match_value
        ]
        if not matches:
            raise SystemExit(
                f"Pin matched no products: {pin.match_field}={pin.match_value!r}"
            )
        if len(matches) > 1:
            raise SystemExit(
                f"Pin matched {len(matches)} products (must be exactly 1): "
                f"{pin.match_field}={pin.match_value!r}"
            )
        idx = matches[0]
        if idx in by_index:
            raise SystemExit(
                f"Two pins both claim the same product (master index {idx}); "
                f"one pin per product please"
            )
        by_index[idx] = pin.seq
    return by_index


# ── Plan builder ─────────────────────────────────────────────────────────────


def _safe_str(value: object) -> str:
    return "" if value is None else str(value)


def build_reissue_plan(
    products: list[dict],
    pin_map: dict[int, int],
) -> list[PlanRow]:
    """Compute the full new-identifier plan deterministically.

    Pinned products land on their reserved seq. Everything else gets the
    next free seq starting at 1, walking the master JSON in its existing
    order (so re-running with the same input + pins produces the same
    plan).
    """
    used_seqs = set(pin_map.values())
    next_seq = 1
    plan: list[PlanRow] = []
    for idx, product in enumerate(products):
        if idx in pin_map:
            seq = pin_map[idx]
        else:
            while next_seq in used_seqs:
                next_seq += 1
            if next_seq > MAX_SEQ:
                raise SystemExit(
                    f"Ran out of EAN-8 sequence space ({MAX_SEQ} max); "
                    f"have {len(products)} products"
                )
            seq = next_seq
            used_seqs.add(seq)
            next_seq += 1
        product_type = _safe_str(product.get("product_type"))
        material = _safe_str(product.get("material"))
        internal_code = _safe_str(product.get("internal_code"))
        new_sku = generate_sku_code(internal_code, material, product_type, seq)
        new_plu = generate_nec_plu(seq)
        plan.append(
            PlanRow(
                index=idx,
                product=product,
                new_seq=seq,
                new_sku_code=new_sku,
                new_nec_plu=new_plu,
                pinned=idx in pin_map,
            )
        )

    # Pre-flight uniqueness check: regenerated SKU codes embed type+material
    # abbreviations, so two products with the same (type, material) at
    # different seqs never collide. But two pins with the same (type,
    # material) but different seqs are fine. The thing we *do* need to
    # guard is duplicate seqs — already guaranteed by used_seqs above —
    # and duplicate SKU codes coming out of the factory (defensive).
    sku_seen: dict[str, int] = {}
    plu_seen: dict[str, int] = {}
    for row in plan:
        if row.new_sku_code in sku_seen:
            raise SystemExit(
                f"Internal error: SKU collision after reissue at seq={row.new_seq} "
                f"({row.new_sku_code}); also at seq={sku_seen[row.new_sku_code]}"
            )
        sku_seen[row.new_sku_code] = row.new_seq
        if row.new_nec_plu in plu_seen:
            raise SystemExit(
                f"Internal error: PLU collision after reissue at seq={row.new_seq} "
                f"({row.new_nec_plu}); also at seq={plu_seen[row.new_nec_plu]}"
            )
        plu_seen[row.new_nec_plu] = row.new_seq

    return plan


# ── Diff CSV + apply ────────────────────────────────────────────────────────


def write_diff_csv(plan: list[PlanRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "master_index",
                "pinned",
                "new_seq",
                "sku_code_old",
                "sku_code_new",
                "nec_plu_old",
                "nec_plu_new",
                "internal_code",
                "product_type",
                "material",
                "description",
            ]
        )
        for row in plan:
            writer.writerow(
                [
                    row.index,
                    "yes" if row.pinned else "",
                    row.new_seq,
                    row.old_sku_code,
                    row.new_sku_code,
                    row.old_nec_plu,
                    row.new_nec_plu,
                    _safe_str(row.product.get("internal_code")),
                    _safe_str(row.product.get("product_type")),
                    _safe_str(row.product.get("material")),
                    _safe_str(row.product.get("description"))[:80],
                ]
            )


def apply_plan(plan: list[PlanRow]) -> None:
    """Mutate each product dict in place with the new identifiers.

    Also regenerates ``google_product_id`` (which embeds sku_code).
    Leaves ``amazon_sku`` alone — it's derived from internal_code, not
    seq, so it stays stable across reissuance.
    """
    for row in plan:
        row.product["sku_code"] = row.new_sku_code
        row.product["nec_plu"] = row.new_nec_plu
        row.product["google_product_id"] = generate_google_product_id(row.new_sku_code)


def backup_master(master_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = master_path.with_suffix(f".{timestamp}.bak.json")
    shutil.copy2(master_path, backup)
    return backup


# ── CLI ──────────────────────────────────────────────────────────────────────


def _summarise_plan(plan: list[PlanRow]) -> dict[str, int]:
    pinned = sum(1 for r in plan if r.pinned)
    sku_changed = sum(1 for r in plan if r.old_sku_code != r.new_sku_code)
    plu_changed = sum(1 for r in plan if r.old_nec_plu != r.new_nec_plu)
    return {
        "total_products": len(plan),
        "pinned": pinned,
        "sku_codes_changed": sku_changed,
        "nec_plus_changed": plu_changed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--master",
        type=Path,
        default=DEFAULT_MASTER,
        help="Path to master_product_list.json",
    )
    parser.add_argument(
        "--pin-file",
        type=Path,
        default=None,
        help="CSV pinning specific products to specific seq numbers",
    )
    parser.add_argument(
        "--diff-csv",
        type=Path,
        default=None,
        help="Where to write the before/after diff CSV (default: data/exports/...)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite the master JSON. Without this, runs as a dry-run.",
    )
    args = parser.parse_args(argv)

    if not args.master.exists():
        print(f"Master JSON not found: {args.master}", file=sys.stderr)
        return 2

    raw = json.loads(args.master.read_text())
    products = raw.get("products")
    if not isinstance(products, list):
        print(f"{args.master} has no 'products' list", file=sys.stderr)
        return 2

    pins = load_pins(args.pin_file)
    pin_map = resolve_pins(pins, products)
    plan = build_reissue_plan(products, pin_map)

    diff_path = args.diff_csv or (
        DEFAULT_DIFF_DIR
        / f"reissue_ean8_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    write_diff_csv(plan, diff_path)

    summary = _summarise_plan(plan)
    print("Reissuance plan:")
    for k, v in summary.items():
        print(f"  {k:>20s}: {v}")
    print(f"  diff CSV          : {diff_path}")

    if not args.apply:
        print()
        print("Dry-run only. Re-run with --apply to write the master JSON.")
        return 0

    backup = backup_master(args.master)
    apply_plan(plan)
    args.master.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    print()
    print(f"Applied. Backup written to: {backup}")
    print("Next: sync the new identifiers to Postgres + Firestore using")
    print("      the existing sync tooling (out of scope for this script).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
