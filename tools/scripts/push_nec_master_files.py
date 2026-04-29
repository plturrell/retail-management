#!/usr/bin/env python3
"""Cron-friendly entrypoint to build the NEC Jewel master TXT bundle and
push it to the CAG SFTP ``Inbound/Working/<tenant>/`` folder.

Usage::

    python tools/scripts/push_nec_master_files.py \\
        --tenant 200151 \\
        --nec-store-id 80001 \\
        --brand "VICTORIA ENSO" \\
        [--store JEWEL-01] \\
        [--airside]            # tax-exclusive pricing for airside stores
        [--dry-run]            # build files only, do not upload

Reads CAG SFTP credentials from environment (``CAG_SFTP_HOST``, ``_USER``,
``_PASSWORD`` / ``_KEY_PATH``) — see ``backend/.env.example``.

Writes a copy of the bundle to ``data/exports/cag_nec_<tenant>_<ts>/``
for audit, alongside any ``--dry-run`` payload.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.firestore import db as fs_db  # noqa: E402
from app.services import cag_sftp  # noqa: E402
from app.services.nec_jewel_bundle import build_master_bundle  # noqa: E402
from app.services.nec_jewel_export import (  # noqa: E402
    BRAND_NAME,
    DEFAULT_INV_STORE_CODE,
    fetch_sellable_skus_from_firestore,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant", help="6/7-digit CAG Customer No (defaults to CAG_SFTP_TENANT_FOLDER)")
    p.add_argument("--nec-store-id", required=True, help="5-digit NEC-assigned Store ID")
    p.add_argument("--brand", default=BRAND_NAME)
    p.add_argument("--store", default=None, help="Filter SKUs by Firestore store_code")
    p.add_argument("--inv-store", default=DEFAULT_INV_STORE_CODE)
    p.add_argument("--include-drafts", action="store_true")
    p.add_argument("--airside", action="store_true", help="Treat store as non-taxable (excl-tax pricing)")
    p.add_argument("--dry-run", action="store_true", help="Build files only; skip SFTP upload")
    p.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "data" / "exports"),
        help="Audit copy destination",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tenant = args.tenant or settings.CAG_SFTP_TENANT_FOLDER
    if not tenant:
        print("ERROR: --tenant is required (or set CAG_SFTP_TENANT_FOLDER)", file=sys.stderr)
        return 2

    print(f"[1/4] Fetching sellable SKUs (brand={args.brand}, store={args.store or 'ALL'})...")
    products, excluded = fetch_sellable_skus_from_firestore(
        fs_db,
        brand_name=args.brand,
        store_code=args.store,
        inv_store_code=args.inv_store,
        include_drafts=args.include_drafts,
    )
    print(f"     -> {len(products)} sellable, {len(excluded)} excluded")
    if not products:
        print("Nothing to upload.", file=sys.stderr)
        return 1

    print(f"[2/4] Building TXT bundle (tenant={tenant}, store_id={args.nec_store_id})...")
    bundle = build_master_bundle(
        products,
        tenant_code=tenant,
        store_id=args.nec_store_id,
        taxable=not args.airside,
    )
    for k, v in bundle.counts.items():
        print(f"     {k:>10}: {v}")

    out_dir = Path(args.out_dir) / f"cag_nec_{tenant}_{bundle.generated_at.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, payload in bundle.files.items():
        (out_dir / fname).write_bytes(payload)
    print(f"[3/4] Audit copy written to {out_dir}")

    if args.dry_run:
        print("[4/4] --dry-run: skipping SFTP upload")
        return 0

    cfg = cag_sftp.SFTPConfig.from_settings()
    if not cag_sftp.is_configured(cfg):
        print("ERROR: CAG SFTP not configured (set CAG_SFTP_HOST/USER + key/password)", file=sys.stderr)
        return 3
    print(f"[4/4] Uploading to {cfg.host}:{cfg.port} {cfg.working_dir}/ ...")
    result = cag_sftp.upload_files(bundle.files, config=cfg)
    print(f"     uploaded {len(result.files_uploaded)} files, {result.bytes_uploaded} bytes")
    if result.errors:
        for err in result.errors:
            print(f"     ERROR: {err}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
