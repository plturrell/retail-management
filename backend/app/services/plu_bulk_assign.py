"""Bulk-assign / repair NEC-aligned EAN-13 PLU barcodes in Firestore.

The data quality dashboard surfaces a count of SKUs without a valid PLU.
This service scans the live Firestore data and either:

* assigns an aligned EAN-13 PLU to each SKU that lacks one, or
* rewrites invalid / misaligned PLUs to their canonical form.

Mirrors the strategy in ``tools/scripts/repair_invalid_plus_codes.py`` but
operates directly on Firestore so the staff portal can run it on demand.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services.identifier_utils import (
    aligned_nec_plu_for_sku,
    generate_nec_plu,
    is_valid_ean13,
    max_sku_sequence,
    max_valid_plu_sequence,
)

log = logging.getLogger(__name__)


@dataclass
class PlanRow:
    sku_id: str
    sku_code: str
    description: str
    old_plu: str | None
    new_plu: str
    reason: str  # "missing" | "invalid" | "misaligned"
    plu_doc_id: str | None  # existing plu doc id, if any

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku_id": self.sku_id,
            "sku_code": self.sku_code,
            "description": self.description,
            "old_plu": self.old_plu,
            "new_plu": self.new_plu,
            "reason": self.reason,
        }


@dataclass
class PlanResult:
    plan: list[PlanRow]
    summary: dict[str, int]
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "summary": dict(self.summary),
            "plan": [r.to_dict() for r in self.plan[:200]],  # cap response size
            "plan_total": len(self.plan),
        }


# ---------------------------------------------------------------------------
# Firestore scan
# ---------------------------------------------------------------------------

def _iter_skus(fs_db: Any) -> Iterable[dict[str, Any]]:
    """Yield SKU dicts from every store's inventory subcollection."""
    for store_snap in fs_db.collection("stores").stream():
        for sku_snap in store_snap.reference.collection("inventory").stream():
            data = sku_snap.to_dict() or {}
            data.setdefault("id", sku_snap.id)
            yield data


def _load_plus(fs_db: Any) -> tuple[dict[str, dict[str, Any]], set[str]]:
    by_sku: dict[str, dict[str, Any]] = {}
    all_codes: set[str] = set()
    for snap in fs_db.collection("plus").stream():
        data = snap.to_dict() or {}
        data.setdefault("id", snap.id)
        sid = data.get("sku_id")
        if sid:
            by_sku[str(sid)] = data
        code = data.get("plu_code")
        if code:
            all_codes.add(str(code))
    return by_sku, all_codes


def _classify(sku: dict[str, Any], plu_doc: dict[str, Any] | None) -> tuple[str, str | None] | None:
    """Decide if this SKU needs repair. Returns ``(reason, old_plu)`` or
    ``None`` if no action is required."""
    sku_code = str(sku.get("sku_code") or "")
    if not sku_code:
        return None
    plu_code = str(plu_doc.get("plu_code") or "") if plu_doc else ""
    if not plu_code:
        return ("missing", None)
    if not is_valid_ean13(plu_code):
        return ("invalid", plu_code)
    expected = aligned_nec_plu_for_sku(sku_code)
    if expected and plu_code != expected:
        return ("misaligned", plu_code)
    return None


def build_plan(fs_db: Any) -> list[PlanRow]:
    plus_by_sku, all_plus = _load_plus(fs_db)
    skus = list(_iter_skus(fs_db))

    plan: list[PlanRow] = []
    sku_codes = [str(s.get("sku_code") or "") for s in skus]
    next_seq = (
        max(
            max_sku_sequence(sku_codes),
            max_valid_plu_sequence(all_plus),
        )
        + 1
    )

    # Build a working set of valid, kept PLUs so we don't reassign them.
    keep: set[str] = set()
    needs_repair: list[tuple[dict[str, Any], dict[str, Any] | None, str, str | None]] = []
    for sku in skus:
        plu_doc = plus_by_sku.get(str(sku.get("id") or ""))
        cls = _classify(sku, plu_doc)
        if cls is None:
            if plu_doc and plu_doc.get("plu_code"):
                keep.add(str(plu_doc["plu_code"]))
            continue
        needs_repair.append((sku, plu_doc, cls[0], cls[1]))

    used = set(keep)
    for sku, plu_doc, reason, old_plu in needs_repair:
        sku_code = str(sku.get("sku_code") or "")
        # First preference: SKU-aligned PLU.
        candidate = aligned_nec_plu_for_sku(sku_code)
        if candidate and candidate not in used:
            new_plu = candidate
        else:
            # Fall back to next free sequence.
            seq = next_seq
            while True:
                cand = generate_nec_plu(seq)
                if cand not in used:
                    new_plu = cand
                    next_seq = seq + 1
                    break
                seq += 1
        used.add(new_plu)
        plan.append(
            PlanRow(
                sku_id=str(sku.get("id") or ""),
                sku_code=sku_code,
                description=str(sku.get("description") or ""),
                old_plu=old_plu,
                new_plu=new_plu,
                reason=reason,
                plu_doc_id=str(plu_doc.get("id")) if plu_doc else None,
            )
        )
    return plan


def _summarise(plan: Iterable[PlanRow]) -> dict[str, int]:
    s = {"missing": 0, "invalid": 0, "misaligned": 0, "total": 0}
    for row in plan:
        s["total"] += 1
        s[row.reason] = s.get(row.reason, 0) + 1
    return s


def _apply(fs_db: Any, plan: list[PlanRow], *, updated_by: str) -> None:
    now = datetime.now(timezone.utc)
    plus_col = fs_db.collection("plus")
    for row in plan:
        if row.plu_doc_id:
            plus_col.document(row.plu_doc_id).update(
                {
                    "plu_code": row.new_plu,
                    "updated_at": now,
                    "updated_by": updated_by,
                    "previous_plu_code": row.old_plu,
                }
            )
        else:
            doc_id = str(uuid.uuid4())
            plus_col.document(doc_id).set(
                {
                    "id": doc_id,
                    "sku_id": row.sku_id,
                    "plu_code": row.new_plu,
                    "created_at": now,
                    "created_by": updated_by,
                    "source": "plu_bulk_assign",
                }
            )


def run(fs_db: Any, *, apply: bool, updated_by: str = "") -> PlanResult:
    plan = build_plan(fs_db)
    summary = _summarise(plan)
    if apply and plan:
        _apply(fs_db, plan, updated_by=updated_by)
    return PlanResult(plan=plan, summary=summary, applied=bool(apply and plan))


__all__ = ["PlanResult", "PlanRow", "build_plan", "run"]
