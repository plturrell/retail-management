"""Tests for the PLU bulk-assign / repair service."""
from __future__ import annotations

from typing import Any

import pytest

from app.services import plu_bulk_assign
from app.services.identifier_utils import (
    aligned_nec_plu_for_sku,
    is_valid_plu,
)


class FakeSnap:
    def __init__(self, doc_id: str, data: dict[str, Any]):
        self.id = doc_id
        self._data = data
        self.reference = FakeRef(self)

    def to_dict(self):
        return dict(self._data)


class FakeRef:
    def __init__(self, snap: "FakeSnap"):
        self._snap = snap

    def collection(self, name: str):
        return self._snap._sub.get(name, FakeCollection({}))


class FakeCollection:
    def __init__(self, store: dict[str, dict[str, Any]]):
        self._store = store

    def stream(self):
        for doc_id, data in list(self._store.items()):
            snap = FakeSnap(doc_id, data)
            yield snap

    def document(self, doc_id: str):
        return FakeDoc(self._store, doc_id)


class FakeDoc:
    def __init__(self, store: dict[str, dict[str, Any]], doc_id: str):
        self._store = store
        self._id = doc_id

    def set(self, data: dict[str, Any]):
        self._store[self._id] = dict(data)

    def update(self, data: dict[str, Any]):
        self._store.setdefault(self._id, {}).update(data)


class FakeFirestore:
    def __init__(self, stores: dict[str, list[dict[str, Any]]], plus: dict[str, dict[str, Any]]):
        # ``stores`` maps store_id -> list[sku dict]; ``plus`` maps plu_id -> dict.
        self._stores = stores
        self._plus = plus

    def collection(self, name: str):
        if name == "plus":
            return FakeCollection(self._plus)
        if name == "stores":
            store_docs: dict[str, dict[str, Any]] = {sid: {} for sid in self._stores}
            stream_objs = []
            for sid, skus in self._stores.items():
                inv_store = {sku["id"]: sku for sku in skus}
                snap = FakeSnap(sid, store_docs[sid])
                snap._sub = {"inventory": FakeCollection(inv_store)}
                stream_objs.append(snap)

            class _Coll:
                def stream(self_inner):
                    return iter(stream_objs)

                def document(self_inner, _):
                    raise NotImplementedError

            return _Coll()
        raise KeyError(name)


@pytest.fixture()
def fs_with_mixed_data() -> FakeFirestore:
    skus = [
        {"id": "sku-1", "sku_code": "VE0000001", "description": "Aligned"},
        {"id": "sku-2", "sku_code": "VE0000002", "description": "Missing PLU"},
        {"id": "sku-3", "sku_code": "VE0000003", "description": "Invalid PLU"},
        {"id": "sku-4", "sku_code": "VE0000004", "description": "Misaligned PLU"},
    ]
    plus = {
        "plu-1": {"id": "plu-1", "sku_id": "sku-1", "plu_code": aligned_nec_plu_for_sku("VE0000001")},
        # sku-2 has no plus doc
        "plu-3": {"id": "plu-3", "sku_id": "sku-3", "plu_code": "12345678"},  # bad EAN-8 checksum
        "plu-4": {"id": "plu-4", "sku_id": "sku-4", "plu_code": aligned_nec_plu_for_sku("VE0000007")},
    }
    return FakeFirestore({"store-1": skus}, plus)


def test_dry_run_lists_only_problematic_skus(fs_with_mixed_data):
    result = plu_bulk_assign.run(fs_with_mixed_data, apply=False)
    assert result.applied is False
    by_sku = {row.sku_code: row for row in result.plan}
    assert "VE0000001" not in by_sku  # already aligned, untouched
    assert by_sku["VE0000002"].reason == "missing"
    assert by_sku["VE0000003"].reason == "invalid"
    assert by_sku["VE0000004"].reason == "misaligned"
    # All proposed PLUs are valid EAN-8.
    for row in result.plan:
        assert is_valid_plu(row.new_plu)


def test_apply_creates_doc_for_missing_and_updates_existing(fs_with_mixed_data):
    result = plu_bulk_assign.run(fs_with_mixed_data, apply=True, updated_by="owner@x")
    assert result.applied is True

    # New plus doc created for sku-2.
    new_docs = [d for d in fs_with_mixed_data._plus.values() if d.get("sku_id") == "sku-2"]
    assert len(new_docs) == 1
    assert is_valid_plu(new_docs[0]["plu_code"])

    # sku-3 / sku-4 docs were updated in place; check no duplicate created.
    sku3_docs = [d for d in fs_with_mixed_data._plus.values() if d.get("sku_id") == "sku-3"]
    sku4_docs = [d for d in fs_with_mixed_data._plus.values() if d.get("sku_id") == "sku-4"]
    assert len(sku3_docs) == 1 and is_valid_plu(sku3_docs[0]["plu_code"])
    assert len(sku4_docs) == 1
    assert sku4_docs[0]["plu_code"] == aligned_nec_plu_for_sku("VE0000004")
    assert sku4_docs[0]["previous_plu_code"] == aligned_nec_plu_for_sku("VE0000007")
    assert sku4_docs[0]["updated_by"] == "owner@x"


def test_idempotent_second_run_is_noop(fs_with_mixed_data):
    plu_bulk_assign.run(fs_with_mixed_data, apply=True, updated_by="owner@x")
    second = plu_bulk_assign.run(fs_with_mixed_data, apply=True, updated_by="owner@x")
    assert second.summary["total"] == 0
    assert second.applied is False  # no plan rows to apply


def test_all_assigned_codes_are_unique():
    """Even when many SKUs need PLUs, the planner never reuses a code."""
    skus = [
        {"id": f"s{i}", "sku_code": f"VE000{i:04d}", "description": f"sku {i}"}
        for i in range(20)
    ]
    fs = FakeFirestore({"s": skus}, {})
    result = plu_bulk_assign.run(fs, apply=False)
    codes = [row.new_plu for row in result.plan]
    assert len(codes) == 20
    assert len(set(codes)) == 20  # no duplicates
    assert all(is_valid_plu(c) for c in codes)
