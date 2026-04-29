from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from typing import Any


class MemoryFirestore:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    def seed(self, collection_path: str, *documents: dict[str, Any]) -> None:
        for document in documents:
            doc_id = str(document["id"])
            self.collections[collection_path][doc_id] = deepcopy(document)

    def create_document(
        self,
        collection_path: str,
        data: dict[str, Any],
        doc_id: str | None = None,
    ) -> dict[str, Any]:
        stored = deepcopy(data)
        resolved_id = doc_id or str(stored.get("id"))
        if not resolved_id:
            raise ValueError("doc_id is required for MemoryFirestore documents")
        if not stored.get("id"):
            stored["id"] = resolved_id
        self.collections[collection_path][resolved_id] = stored
        return deepcopy(stored)

    def get_document(self, collection_path: str, doc_id: str) -> dict[str, Any] | None:
        document = self.collections[collection_path].get(doc_id)
        return deepcopy(document) if document is not None else None

    def update_document(
        self,
        collection_path: str,
        doc_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if doc_id not in self.collections[collection_path]:
            raise KeyError(f"{collection_path}/{doc_id} not found")
        current = deepcopy(self.collections[collection_path][doc_id])
        current.update(deepcopy(data))
        self.collections[collection_path][doc_id] = current
        return deepcopy(current)

    def query_collection(
        self,
        collection_path: str,
        filters: tuple[tuple[str, str, Any], ...] = (),
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = [deepcopy(item) for item in self.collections[collection_path].values()]
        for field, op, value in filters:
            rows = [row for row in rows if self._matches(row.get(field), op, value)]

        if order_by:
            descending = order_by.startswith("-")
            field_name = order_by.lstrip("-")
            rows.sort(
                key=lambda row: self._sort_value(row.get(field_name)),
                reverse=descending,
            )

        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    @staticmethod
    def _sort_value(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, date):
            return value.toordinal()
        return value

    @classmethod
    def _matches(cls, left: Any, op: str, right: Any) -> bool:
        if op == "==":
            return left == right

        left_value = cls._sort_value(left)
        right_value = cls._sort_value(right)

        if op == ">=":
            return left_value >= right_value
        if op == "<=":
            return left_value <= right_value
        if op == ">":
            return left_value > right_value
        if op == "<":
            return left_value < right_value

        raise NotImplementedError(f"MemoryFirestore does not support {op} filters")
