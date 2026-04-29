#!/usr/bin/env python3
"""
One-time migration script: PostgreSQL → Firestore.

Reads all relevant tables from a PostgreSQL database and writes them
into Firestore collections using the same document IDs (PG primary keys).
Idempotent — safe to re-run; existing documents are overwritten with
the same deterministic ID.

Requirements (migration-only, not in main requirements.txt):
    pip install sqlalchemy psycopg2-binary firebase-admin google-cloud-firestore

Usage:
    python -m backend.tools.migrate_postgres_to_firestore --pg-url "postgresql://..." [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import decimal
import json
import logging
import sys
import uuid
from typing import Any, Dict, List, Sequence

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.client import Client as FirestoreClient
from sqlalchemy import create_engine, inspect, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("pg2firestore")

# ── Table → Firestore collection mapping ────────────────────────────────
# Keys are PostgreSQL table names; values are Firestore collection paths.
# Sub-collections (e.g. stores/{id}/inventory) are handled specially below.
TABLE_MAP: Dict[str, str] = {
    "users": "users",
    "stores": "stores",
    "employees": "employees",
    "timesheets": "timesheets",
    "schedules": "schedules",
    "orders": "orders",
    "payroll_runs": "payroll-runs",
    "payslips": "payslips",
    "commission_rules": "commission-rules",
    "inventory": "inventory",
    "categories": "categories",
    "brands": "brands",
    "skus": "skus",
    "promotions": "promotions",
    "prices": "prices",
    "accounts": "accounts",
    "journal_entries": "journal-entries",
    "banking_transactions": "banking-transactions",
    "ai_invocations": "ai-invocations",
}

# Tables whose Firestore doc should be nested under stores/{store_id}/…
STORE_SCOPED: Dict[str, str] = {
    "inventory": "inventory",
    "categories": "categories",
    "skus": "skus",
    "orders": "orders",
    "timesheets": "timesheets",
    "schedules": "schedules",
    "journal_entries": "journal-entries",
    "banking_transactions": "banking-transactions",
}

# Column name that holds the PG primary key (used as Firestore doc ID).
PK_COLUMN = "id"


# ── Helpers ──────────────────────────────────────────────────────────────

def _convert_value(val: Any) -> Any:
    """Convert Python/PG types to Firestore-safe types."""
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    if isinstance(val, datetime.time):
        return val.isoformat()
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, dict):
        return {k: _convert_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_convert_value(v) for v in val]
    return val



# ── Core migration logic ────────────────────────────────────────────────

def _migrate_table(
    engine,
    fs_client: FirestoreClient,
    pg_table: str,
    fs_collection: str,
    *,
    dry_run: bool = False,
) -> int:
    """Migrate a single PG table to a Firestore collection. Returns row count."""
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT * FROM "{pg_table}"'))  # noqa: S608
        columns = list(result.keys())
        rows = [dict(zip(columns, r)) for r in result.fetchall()]

    if not rows:
        log.info("  %-25s → %-25s  (0 rows — skipped)", pg_table, fs_collection)
        return 0

    batch_size = 450  # Firestore batch limit is 500; leave headroom
    written = 0

    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        batch = fs_client.batch()

        for row in chunk:
            doc_id = _get_doc_id(row)
            doc_data = _row_to_doc(row)

            # Decide collection path: store-scoped or top-level
            if pg_table in STORE_SCOPED and "store_id" in row:
                store_id = str(row["store_id"])
                col_path = f"stores/{store_id}/{STORE_SCOPED[pg_table]}"
            else:
                col_path = fs_collection

            ref = fs_client.collection(col_path).document(doc_id)
            if not dry_run:
                batch.set(ref, doc_data)
            written += 1

        if not dry_run:
            batch.commit()

    log.info("  %-25s → %-25s  (%d rows)", pg_table, fs_collection, written)
    return written


def _discover_tables(engine) -> List[str]:
    """Return the list of user tables present in the PG database."""
    inspector = inspect(engine)
    return inspector.get_table_names()


def migrate(pg_url: str, *, dry_run: bool = False) -> None:
    """Run the full migration."""
    log.info("Connecting to PostgreSQL …")
    engine = create_engine(pg_url)

    # Verify connectivity
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    log.info("PostgreSQL connection OK")

    # Initialize Firebase
    log.info("Initializing Firebase Admin SDK …")
    try:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    except ValueError:
        firebase_admin.get_app()
    fs_client: FirestoreClient = firestore.client()
    log.info("Firestore client ready")

    available_tables = set(_discover_tables(engine))
    log.info("PG tables found: %s", ", ".join(sorted(available_tables)))

    total = 0
    mode = "DRY-RUN" if dry_run else "LIVE"
    log.info("Starting migration (%s) …", mode)
    log.info("-" * 60)

    for pg_table, fs_collection in TABLE_MAP.items():
        if pg_table not in available_tables:
            log.warning("  %-25s  (table not found — skipped)", pg_table)
            continue
        count = _migrate_table(
            engine, fs_client, pg_table, fs_collection, dry_run=dry_run,
        )
        total += count

    # Catch any unmapped tables
    unmapped = available_tables - set(TABLE_MAP.keys()) - {"alembic_version"}
    if unmapped:
        log.warning("Unmapped PG tables (not migrated): %s", ", ".join(sorted(unmapped)))

    log.info("-" * 60)
    log.info("Migration complete. Total rows processed: %d (%s)", total, mode)


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate PostgreSQL data to Firestore",
    )
    parser.add_argument(
        "--pg-url",
        required=True,
        help="PostgreSQL connection URL, e.g. postgresql://user:pass@host:5432/dbname",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be migrated without writing to Firestore",
    )
    args = parser.parse_args()
    migrate(args.pg_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()


def _get_doc_id(row: dict) -> str:
    """Extract and stringify the primary key for use as Firestore doc ID."""
    pk = row.get(PK_COLUMN)
    if pk is None:
        raise ValueError(f"Row missing '{PK_COLUMN}' column: {list(row.keys())}")
    return str(pk)
