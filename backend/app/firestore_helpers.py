"""
Reusable Firestore helper functions for RetailSG.

Provides CRUD operations, filtering, pagination, and batch writes
on top of the Firestore client.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from google.cloud.firestore_v1 import DocumentSnapshot
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.firestore import db


# ---------------------------------------------------------------------------
# Document conversion
# ---------------------------------------------------------------------------

def doc_to_dict(doc_snapshot: DocumentSnapshot) -> Dict[str, Any] | None:
    """Convert a Firestore DocumentSnapshot to a dict with 'id' included."""
    if not doc_snapshot.exists:
        return None
    data = doc_snapshot.to_dict() or {}
    if not data.get("id"):
        data["id"] = doc_snapshot.id
    return data


# ---------------------------------------------------------------------------
# Single-document helpers
# ---------------------------------------------------------------------------

def get_document(collection_path: str, doc_id: str) -> Dict[str, Any] | None:
    """Fetch a single document by ID. Returns None if not found."""
    doc = db.collection(collection_path).document(doc_id).get()
    return doc_to_dict(doc)


def create_document(
    collection_path: str,
    data: Dict[str, Any],
    doc_id: str | None = None,
) -> Dict[str, Any]:
    """Create a document. If *doc_id* is None Firestore auto-generates one."""
    if doc_id:
        ref = db.collection(collection_path).document(doc_id)
        ref.set(data)
    else:
        ref = db.collection(collection_path).add(data)[1]
    created = dict(data)
    if not created.get("id"):
        created["id"] = ref.id
    return created


def update_document(
    collection_path: str,
    doc_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Update (merge) fields on an existing document."""
    ref = db.collection(collection_path).document(doc_id)
    ref.update(data)
    # Return the full document after update
    return doc_to_dict(ref.get())


def delete_document(collection_path: str, doc_id: str) -> bool:
    """Delete a document. Returns True on success."""
    db.collection(collection_path).document(doc_id).delete()
    return True


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

FilterTuple = Tuple[str, str, Any]  # ("field", "op", value)


def query_collection(
    collection_path: str,
    filters: Sequence[FilterTuple] = (),
    order_by: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> List[Dict[str, Any]]:
    """Query a collection with optional filters, ordering, limit and offset."""
    ref = db.collection(collection_path)
    query = ref

    for field, op, value in filters:
        query = query.where(field, op, value)

    if order_by:
        from google.cloud.firestore_v1 import query as fq
        direction = fq.Query.DESCENDING if order_by.startswith("-") else fq.Query.ASCENDING
        field_name = order_by.lstrip("-")
        query = query.order_by(field_name, direction=direction)

    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)

    return [doc_to_dict(doc) for doc in query.stream()]



# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginated_query(
    collection_path: str,
    filters: Sequence[FilterTuple] = (),
    page: int = 1,
    page_size: int = 20,
    order_by: str | None = None,
) -> Dict[str, Any]:
    """Return a paginated result set.

    Returns::

        {
            "items": [...],
            "total": <int>,
            "page": <int>,
            "pages": <int>,
        }
    """
    # Count total matching documents
    ref = db.collection(collection_path)
    count_query = ref
    for field, op, value in filters:
        count_query = count_query.where(field, op, value)

    # Firestore aggregation count
    total = count_query.count().get()[0][0].value

    offset = (page - 1) * page_size
    items = query_collection(
        collection_path,
        filters=filters,
        order_by=order_by,
        limit=page_size,
        offset=offset,
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": math.ceil(total / page_size) if page_size else 1,
    }


# ---------------------------------------------------------------------------
# Batch writes
# ---------------------------------------------------------------------------

def batch_write(operations: List[Dict[str, Any]]) -> bool:
    """Execute multiple write operations atomically.

    Each operation is a dict with keys:
        - "action": "create" | "update" | "delete"
        - "collection": collection path
        - "doc_id": document ID (optional for create)
        - "data": dict (required for create/update)

    Returns True on success.
    """
    batch = db.batch()

    for op in operations:
        action = op["action"]
        collection = op["collection"]
        doc_id = op.get("doc_id")

        if action == "create":
            if doc_id:
                ref = db.collection(collection).document(doc_id)
            else:
                ref = db.collection(collection).document()
            batch.set(ref, op["data"])
        elif action == "update":
            ref = db.collection(collection).document(doc_id)
            batch.update(ref, op["data"])
        elif action == "delete":
            ref = db.collection(collection).document(doc_id)
            batch.delete(ref)
        else:
            raise ValueError(f"Unknown batch action: {action}")

    batch.commit()
    return True
