#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from identifier_utils import (
    aligned_nec_plu_for_sku,
    is_valid_ean13,
    is_valid_plu,
    parse_sku_sequence,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT_DIR = REPO_ROOT / "data" / "exports"
DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)


@dataclass(frozen=True)
class SourcePlusRow:
    sku_code: str
    legacy_code: str | None
    description: str
    form_factor: str | None
    plu_code: str


@dataclass(frozen=True)
class AlignmentAuditRow:
    sku_code: str
    sku_format: str
    sku_sequence: int | None
    legacy_code: str | None
    description: str
    form_factor: str | None
    current_plu: str
    current_valid_ean13: bool
    expected_aligned_plu: str | None
    row_status: str
    target_status: str
    target_sku_code: str | None
    target_legacy_code: str | None
    target_description: str | None
    target_row_status: str | None
    recommended_action: str


FETCH_SQL = text(
    """
    SELECT
        s.sku_code,
        s.legacy_code,
        s.description,
        s.form_factor,
        p.plu_code
    FROM plus p
    JOIN skus s ON s.id = p.sku_id
    ORDER BY s.sku_code
    """
)


def classify_row_status(row: SourcePlusRow) -> tuple[str, str | None, bool]:
    current_plu = str(row.plu_code)
    # Audit is a migration tool: a legacy EAN-13 PLU is "valid in its own
    # format" even though new issuance is EAN-8. Treat either format as a
    # well-formed current PLU so the action recommendation can distinguish
    # "legacy code worth re-issuing" from genuine garbage.
    current_valid = is_valid_plu(current_plu) or is_valid_ean13(current_plu)
    expected = aligned_nec_plu_for_sku(row.sku_code)
    if expected is None:
        return ("legacy_valid_unmapped" if current_valid else "legacy_invalid_unmapped"), expected, current_valid
    if current_valid and expected == current_plu:
        return "aligned", expected, current_valid
    if not current_valid:
        return "invalid", expected, current_valid
    return "misaligned_valid", expected, current_valid


def infer_sku_format(sku_code: str) -> str:
    if sku_code.startswith("VE") and parse_sku_sequence(sku_code) is not None:
        return "ve_7digit_sequence"
    if sku_code.startswith("GEN-"):
        return "legacy_gen"
    return "other"


def build_alignment_audit(
    rows: list[SourcePlusRow],
    *,
    include_aligned: bool = False,
) -> list[AlignmentAuditRow]:
    base_rows: list[dict[str, object]] = []
    by_current_plu: dict[str, dict[str, object]] = {}

    for row in rows:
        row_status, expected_aligned_plu, current_valid = classify_row_status(row)
        current_plu = str(row.plu_code)
        base = {
            "sku_code": row.sku_code,
            "sku_format": infer_sku_format(row.sku_code),
            "sku_sequence": parse_sku_sequence(row.sku_code),
            "legacy_code": row.legacy_code,
            "description": row.description,
            "form_factor": row.form_factor,
            "current_plu": current_plu,
            "current_valid_ean13": current_valid,
            "expected_aligned_plu": expected_aligned_plu,
            "row_status": row_status,
        }
        base_rows.append(base)
        by_current_plu[current_plu] = base

    audit_rows: list[AlignmentAuditRow] = []
    for base in base_rows:
        row_status = str(base["row_status"])
        expected_aligned_plu = base["expected_aligned_plu"]
        target_status = "no_expected"
        target_sku_code = None
        target_legacy_code = None
        target_description = None
        target_row_status = None
        recommended_action = "manual_review"

        if row_status == "aligned":
            target_status = "self"
            recommended_action = "keep"
        elif row_status.endswith("_unmapped"):
            target_status = "no_sequence_rule"
            recommended_action = "manual_review_define_legacy_mapping"
        elif expected_aligned_plu:
            target = by_current_plu.get(str(expected_aligned_plu))
            if not target:
                target_status = "free"
                recommended_action = "set_to_aligned"
            else:
                target_sku_code = str(target["sku_code"])
                target_legacy_code = target["legacy_code"]
                target_description = target["description"]
                target_row_status = str(target["row_status"])
                if target_sku_code == base["sku_code"]:
                    target_status = "self"
                    recommended_action = "manual_review"
                else:
                    target_status = f"occupied_by_{target_row_status}"
                    recommended_action = (
                        "swap_or_staged_realign"
                        if target_row_status != "aligned"
                        else "manual_review"
                    )

        audit_row = AlignmentAuditRow(
            sku_code=str(base["sku_code"]),
            sku_format=str(base["sku_format"]),
            sku_sequence=base["sku_sequence"],  # type: ignore[arg-type]
            legacy_code=base["legacy_code"],  # type: ignore[arg-type]
            description=str(base["description"]),
            form_factor=base["form_factor"],  # type: ignore[arg-type]
            current_plu=str(base["current_plu"]),
            current_valid_ean13=bool(base["current_valid_ean13"]),
            expected_aligned_plu=expected_aligned_plu if isinstance(expected_aligned_plu, str) else None,
            row_status=row_status,
            target_status=target_status,
            target_sku_code=target_sku_code,
            target_legacy_code=target_legacy_code,
            target_description=target_description,
            target_row_status=target_row_status,
            recommended_action=recommended_action,
        )
        if include_aligned or audit_row.row_status != "aligned":
            audit_rows.append(audit_row)

    return audit_rows


def build_summary(
    all_rows: list[SourcePlusRow],
    audit_rows: list[AlignmentAuditRow],
    *,
    include_aligned: bool,
) -> dict[str, object]:
    row_status_counts = Counter(classify_row_status(row)[0] for row in all_rows)
    target_status_counts = Counter(row.target_status for row in audit_rows)
    action_counts = Counter(row.recommended_action for row in audit_rows)
    by_type = Counter(row.form_factor or "UNKNOWN" for row in audit_rows)
    sku_format_counts = Counter(row.sku_format for row in audit_rows)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "include_aligned_rows_in_csv": include_aligned,
        "total_plus_rows": len(all_rows),
        "csv_row_count": len(audit_rows),
        "row_status_counts": dict(row_status_counts),
        "target_status_counts": dict(target_status_counts),
        "recommended_action_counts": dict(action_counts),
        "sku_format_counts": dict(sku_format_counts),
        "top_form_factors": dict(by_type.most_common(25)),
    }


async def fetch_plus_rows(database_url: str) -> list[SourcePlusRow]:
    engine = create_async_engine(database_url, echo=False)
    async with engine.connect() as conn:
        rows = [SourcePlusRow(**dict(row._mapping)) for row in await conn.execute(FETCH_SQL)]
    await engine.dispose()
    return rows


def write_csv(path: Path, rows: list[AlignmentAuditRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()) if rows else list(AlignmentAuditRow.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


async def run(database_url: str, csv_path: Path, json_path: Path, include_aligned: bool) -> None:
    source_rows = await fetch_plus_rows(database_url)
    audit_rows = build_alignment_audit(source_rows, include_aligned=include_aligned)
    summary = build_summary(source_rows, audit_rows, include_aligned=include_aligned)

    write_csv(csv_path, audit_rows)
    write_json(json_path, summary)

    print(f"CSV rows written : {len(audit_rows)}")
    print(f"CSV output       : {csv_path}")
    print(f"Summary output   : {json_path}")
    print(f"Status counts    : {summary['row_status_counts']}")
    print(f"Action counts    : {summary['recommended_action_counts']}")


def main() -> None:
    today = datetime.now().strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="Export an audit of SKU↔PLU alignment in Postgres")
    parser.add_argument("--db-url", default=DEFAULT_DATABASE_URL, help="Database URL")
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_EXPORT_DIR / f"plus_alignment_audit_{today}.csv"),
        help="Output CSV path",
    )
    parser.add_argument(
        "--summary-json",
        default=str(DEFAULT_EXPORT_DIR / f"plus_alignment_audit_{today}_summary.json"),
        help="Output summary JSON path",
    )
    parser.add_argument(
        "--include-aligned",
        action="store_true",
        help="Include already aligned rows in the CSV",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            database_url=args.db_url,
            csv_path=Path(args.csv),
            json_path=Path(args.summary_json),
            include_aligned=args.include_aligned,
        )
    )


if __name__ == "__main__":
    main()
