#!/usr/bin/env python3
"""
OCR Document Lineage Tracker — prevents duplicate processing and provides audit trail.

Tracks every document that enters an OCR pipeline with:
  - file hash (SHA-256) to detect re-processing
  - pipeline name, timestamps, output paths
  - page count, item count from extraction
  - status (pending → processed → reviewed → imported)

Usage as a library:
    from ocr_lineage import LineageTracker
    tracker = LineageTracker()
    if tracker.already_processed(file_path):
        print("Skipping — already processed")
    else:
        record = tracker.start(file_path, pipeline="supplier_ocr")
        ...  # do OCR work
        tracker.finish(record["id"], items_extracted=42, output_paths=[...])
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LINEAGE_PATH = REPO_ROOT / "data" / "ocr_lineage.json"


def _file_hash(path: Path) -> str:
    """SHA-256 of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_id(file_path: Path, pipeline: str) -> str:
    """Deterministic ID from file path + pipeline."""
    return hashlib.sha256(f"{pipeline}:{file_path}".encode()).hexdigest()[:16]


class LineageTracker:
    """Manages the OCR lineage ledger (data/ocr_lineage.json)."""

    def __init__(self, path: Path | str = DEFAULT_LINEAGE_PATH):
        self.path = Path(path)
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            self.records: list[dict[str, Any]] = raw.get("records", [])
            self.meta: dict[str, Any] = raw.get("meta", {})
        else:
            self.records = []
            self.meta = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.meta["total_records"] = len(self.records)
        self.meta["total_processed"] = sum(
            1 for r in self.records if r.get("status") in ("processed", "reviewed", "imported")
        )
        payload = {"meta": self.meta, "records": self.records}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))

    def _index(self) -> dict[str, dict[str, Any]]:
        return {r["id"]: r for r in self.records}

    def find_by_hash(self, sha256: str, pipeline: str = "") -> dict[str, Any] | None:
        for r in self.records:
            if r.get("sha256") == sha256:
                if pipeline and r.get("pipeline") != pipeline:
                    continue
                return r
        return None

    def find_by_path(self, file_path: Path, pipeline: str = "") -> dict[str, Any] | None:
        rel = str(file_path)
        for r in self.records:
            if r.get("source_path") == rel or r.get("source_path_absolute") == str(file_path.resolve()):
                if pipeline and r.get("pipeline") != pipeline:
                    continue
                return r
        return None

    def already_processed(self, file_path: Path, pipeline: str = "") -> bool:
        """Check if a file has already been successfully processed."""
        sha = _file_hash(file_path)
        record = self.find_by_hash(sha, pipeline)
        if record and record.get("status") in ("processed", "reviewed", "imported"):
            return True
        return False

    def start(
        self,
        file_path: Path,
        pipeline: str,
        *,
        supplier: str = "",
        document_type: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Register a document as processing. Returns the lineage record."""
        sha = _file_hash(file_path)
        rid = _make_id(file_path, pipeline)

        # Check for existing record with same ID
        idx = self._index()
        if rid in idx:
            existing = idx[rid]
            existing["status"] = "processing"
            existing["sha256"] = sha
            existing["last_attempt_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            existing["attempt_count"] = existing.get("attempt_count", 0) + 1
            self._save()
            return existing

        try:
            rel_path = str(file_path.resolve().relative_to(REPO_ROOT))
        except ValueError:
            rel_path = str(file_path)

        record: dict[str, Any] = {
            "id": rid,
            "source_path": rel_path,
            "source_path_absolute": str(file_path.resolve()),
            "filename": file_path.name,
            "file_size_bytes": file_path.stat().st_size,
            "sha256": sha,
            "pipeline": pipeline,
            "supplier": supplier,
            "document_type": document_type,
            "status": "processing",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finished_at": None,
            "attempt_count": 1,
            "pages_processed": 0,
            "items_extracted": 0,
            "output_paths": [],
            "notes": notes,
            "errors": [],
        }
        self.records.append(record)
        self._save()
        return record

    def finish(
        self,
        record_id: str,
        *,
        pages_processed: int = 0,
        items_extracted: int = 0,
        output_paths: list[str] | None = None,
        status: str = "processed",
        notes: str = "",
    ) -> dict[str, Any] | None:
        """Mark a document as finished processing."""
        idx = self._index()
        record = idx.get(record_id)
        if not record:
            return None
        record["status"] = status
        record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        record["pages_processed"] = pages_processed
        record["items_extracted"] = items_extracted
        if output_paths:
            record["output_paths"] = output_paths
        if notes:
            record["notes"] = notes
        self._save()
        return record

    def fail(self, record_id: str, error: str) -> dict[str, Any] | None:
        """Mark a document as failed."""
        idx = self._index()
        record = idx.get(record_id)
        if not record:
            return None
        record["status"] = "failed"
        record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        record["errors"].append({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "message": error})
        self._save()
        return record

    def summary(self) -> dict[str, Any]:
        """Return a summary of all tracked documents."""
        from collections import Counter
        statuses = Counter(r["status"] for r in self.records)
        pipelines = Counter(r["pipeline"] for r in self.records)
        suppliers = Counter(r.get("supplier", "") for r in self.records if r.get("supplier"))
        return {
            "total_documents": len(self.records),
            "by_status": dict(statuses.most_common()),
            "by_pipeline": dict(pipelines.most_common()),
            "by_supplier": dict(suppliers.most_common()),
            "total_items_extracted": sum(r.get("items_extracted", 0) for r in self.records),
            "total_pages_processed": sum(r.get("pages_processed", 0) for r in self.records),
        }

    def print_summary(self) -> None:
        s = self.summary()
        print(f"\n{'='*60}")
        print(f"  OCR DOCUMENT LINEAGE — {s['total_documents']} documents tracked")
        print(f"{'='*60}")
        print(f"  Status:    {s['by_status']}")
        print(f"  Pipelines: {s['by_pipeline']}")
        if s["by_supplier"]:
            print(f"  Suppliers: {s['by_supplier']}")
        print(f"  Total pages:  {s['total_pages_processed']}")
        print(f"  Total items:  {s['total_items_extracted']}")


# ── CLI — standalone usage ────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="OCR Document Lineage Tracker")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("summary", help="Show lineage summary")

    list_cmd = sub.add_parser("list", help="List all tracked documents")
    list_cmd.add_argument("--pipeline", default="", help="Filter by pipeline name")
    list_cmd.add_argument("--status", default="", help="Filter by status")

    check_cmd = sub.add_parser("check", help="Check if a file has been processed")
    check_cmd.add_argument("file", type=Path, help="File path to check")
    check_cmd.add_argument("--pipeline", default="", help="Pipeline name")

    args = parser.parse_args()
    tracker = LineageTracker()

    if args.command == "summary" or not args.command:
        tracker.print_summary()

    elif args.command == "list":
        for r in tracker.records:
            if args.pipeline and r["pipeline"] != args.pipeline:
                continue
            if args.status and r["status"] != args.status:
                continue
            status_icon = {"processed": "✓", "failed": "✗", "processing": "…", "reviewed": "★", "imported": "◆"}.get(r["status"], "?")
            print(f"  {status_icon} [{r['pipeline']:20s}] {r['filename']:45s}  {r['status']:12s}  items={r.get('items_extracted', 0)}")

    elif args.command == "check":
        fp = args.file.resolve()
        if not fp.exists():
            print(f"File not found: {fp}")
            return
        processed = tracker.already_processed(fp, args.pipeline)
        record = tracker.find_by_hash(_file_hash(fp), args.pipeline)
        if processed:
            print(f"ALREADY PROCESSED: {fp.name}")
            print(f"  Pipeline: {record['pipeline']}")
            print(f"  Processed at: {record.get('finished_at', '?')}")
            print(f"  Items extracted: {record.get('items_extracted', 0)}")
        else:
            print(f"NOT PROCESSED: {fp.name}")


if __name__ == "__main__":
    main()
