#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from identifier_utils import (
    aligned_nec_plu_for_sku,
    generate_nec_plu,
    is_valid_ean13,
    max_sku_sequence,
    max_valid_plu_sequence,
    parse_sku_sequence,
)

DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://retailsg:RetailSG2026Secure@127.0.0.1:5434/retailsg",
)


@dataclass
class InvalidPlusRow:
    plus_id: str
    sku_code: str
    legacy_code: str | None
    description: str
    old_plu: str


FETCH_SQL = text(
    """
    SELECT
        p.id AS plus_id,
        s.sku_code,
        s.legacy_code,
        s.description,
        p.plu_code AS old_plu
    FROM plus p
    JOIN skus s ON s.id = p.sku_id
    ORDER BY s.sku_code
    """
)

UPDATE_SQL = text("UPDATE plus SET plu_code = :new_plu WHERE id = :plus_id")


def choose_replacement_plu(
    row: InvalidPlusRow,
    *,
    occupied_by: dict[str, str],
    change_ids: set[str],
    allocated_plus: set[str],
    next_seq: int,
) -> tuple[str, int]:
    preferred = aligned_nec_plu_for_sku(row.sku_code)
    if preferred:
        holder = occupied_by.get(preferred)
        if preferred not in allocated_plus and (holder is None or holder in change_ids or holder == row.plus_id):
            allocated_plus.add(preferred)
            return preferred, next_seq

    seq = max(1, next_seq)
    while True:
        candidate = generate_nec_plu(seq)
        if candidate not in allocated_plus:
            allocated_plus.add(candidate)
            return candidate, seq + 1
        seq += 1


async def run(apply: bool, database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)
    async with engine.connect() as conn:
        rows = [InvalidPlusRow(**dict(row._mapping)) for row in await conn.execute(FETCH_SQL)]

        occupied_by = {str(row.old_plu): row.plus_id for row in rows}
        invalid_rows = [row for row in rows if not is_valid_ean13(str(row.old_plu))]
        misaligned_valid_rows = [
            row
            for row in rows
            if is_valid_ean13(str(row.old_plu))
            and aligned_nec_plu_for_sku(row.sku_code)
            and str(row.old_plu) != aligned_nec_plu_for_sku(row.sku_code)
        ]
        rows_needing_repair = invalid_rows + misaligned_valid_rows
        change_ids = {row.plus_id for row in rows_needing_repair}
        allocated_plus = {
            str(row.old_plu)
            for row in rows
            if row.plus_id not in change_ids and is_valid_ean13(str(row.old_plu))
        }
        next_seq = max(
            max_sku_sequence(row.sku_code for row in rows),
            max_valid_plu_sequence(row.old_plu for row in rows),
        ) + 1

        plan: list[tuple[InvalidPlusRow, str]] = []
        for row in rows_needing_repair:
            new_plu, next_seq = choose_replacement_plu(
                row,
                occupied_by=occupied_by,
                change_ids=change_ids,
                allocated_plus=allocated_plus,
                next_seq=next_seq,
            )
            plan.append((row, new_plu))

        print(f"Invalid PLUs found: {len(invalid_rows)}")
        print(f"Valid but misaligned PLUs found: {len(misaligned_valid_rows)}")
        print(f"Total rows to repair: {len(plan)}")
        for row, new_plu in plan[:50]:
            print(
                f"{row.sku_code:18s}  {str(row.legacy_code or ''):12s}  "
                f"{row.old_plu} -> {new_plu}  {row.description[:60]}"
            )

        if not apply:
            print("\n(dry run — no database rows updated. Re-run with --apply to persist.)")
            await engine.dispose()
            return

    async with engine.begin() as conn:
        for index, (row, _) in enumerate(plan, start=1):
            await conn.execute(
                UPDATE_SQL,
                {"plus_id": row.plus_id, "new_plu": f"TEMPPLU{index:08d}"},
            )
        for row, new_plu in plan:
            await conn.execute(UPDATE_SQL, {"plus_id": row.plus_id, "new_plu": new_plu})

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT s.sku_code, p.plu_code
                FROM plus p
                JOIN skus s ON s.id = p.sku_id
                """
            )
        )
        invalid_after: list[str] = []
        misaligned_after: list[tuple[str, str]] = []
        for sku_code, plu_code in result:
            plu = str(plu_code)
            if not is_valid_ean13(plu):
                invalid_after.append(plu)
            elif aligned_nec_plu_for_sku(sku_code) != plu:
                misaligned_after.append((sku_code, plu))
        print(f"\nUpdated {len(plan)} plus rows.")
        print(f"Invalid PLUs remaining: {len(invalid_after)}")
        print(f"Misaligned valid PLUs remaining: {len(misaligned_after)}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair invalid EAN-13 PLUs in Postgres plus table")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--db-url", default=DEFAULT_DATABASE_URL, help="Database URL")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, database_url=args.db_url))


if __name__ == "__main__":
    main()
