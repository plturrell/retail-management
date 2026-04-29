from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from app.firestore_helpers import get_document, query_collection


@dataclass(frozen=True)
class CanonicalStoreIdentity:
    code: str
    name: str
    aliases: tuple[str, ...]


CANONICAL_STORES: tuple[CanonicalStoreIdentity, ...] = (
    CanonicalStoreIdentity(
        code="BREEZE-01",
        name="Breeze",
        aliases=(
            "breeze",
            "breeze by east",
            "victoriaenso breeze by east",
            "victoria enso breeze by east",
            "breeze by east hq warehouse",
            "breeze by east hq and warehouse",
            "hq warehouse",
            "hq",
        ),
    ),
    CanonicalStoreIdentity(
        code="JEWEL-01",
        name="Jewel",
        aliases=(
            "jewel",
            "jewel changi",
            "jewel changi airport",
            "victoriaenso jewel changi",
            "victoria enso jewel changi",
            "jewel b1 241",
            "jewel-b1-241",
        ),
    ),
    CanonicalStoreIdentity(
        code="TAKA-01",
        name="Takashimaya",
        aliases=(
            "taka",
            "takashimaya",
            "takashimaya shopping centre",
            "victoriaenso takashimaya",
            "victoria enso takashimaya",
        ),
    ),
    CanonicalStoreIdentity(
        code="ISETAN-01",
        name="Isetan",
        aliases=(
            "isetan",
            "isetan scotts",
            "victoriaenso isetan scotts",
            "victoria enso isetan scotts",
            "shaw house",
        ),
    ),
    CanonicalStoreIdentity(
        code="ONLINE-01",
        name="Online",
        aliases=(
            "online",
            "online store",
            "website",
            "webstore",
            "web store",
            "ecommerce",
            "e-commerce",
            "shopify",
        ),
    ),
)


_STORE_CODE_RE = re.compile(r"^[A-Z0-9]+-\d+$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_ALIASES_TO_CODE = {
    _NON_ALNUM_RE.sub("", alias.lower()): store.code
    for store in CANONICAL_STORES
    for alias in (store.code, store.name, *store.aliases)
}


def _normalize_store_token(value: str | None) -> str:
    if not value:
        return ""
    return _NON_ALNUM_RE.sub("", value.strip().lower())


def canonical_store_code_for_value(value: str | None) -> str | None:
    normalized = _normalize_store_token(value)
    if not normalized:
        return None
    return _ALIASES_TO_CODE.get(normalized)


def canonicalize_store_code_input(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    canonical = canonical_store_code_for_value(stripped)
    if canonical:
        return canonical
    upper = stripped.upper()
    if _STORE_CODE_RE.match(upper):
        return upper
    return stripped


def infer_canonical_store_code_from_document(store: Mapping[str, Any]) -> str | None:
    for field in ("store_code", "name", "location", "address"):
        code = canonical_store_code_for_value(str(store.get(field, "") or ""))
        if code:
            return code
    return None


def _store_timestamp_key(store: Mapping[str, Any]) -> str:
    updated = store.get("updated_at")
    created = store.get("created_at")
    return f"{updated or ''}|{created or ''}|{store.get('id') or ''}"


def _field_exact_match(store: Mapping[str, Any], reference: str) -> bool:
    normalized_reference = _normalize_store_token(reference)
    if not normalized_reference:
        return False
    return any(
        _normalize_store_token(str(store.get(field, "") or "")) == normalized_reference
        for field in ("store_code", "name", "location", "address")
    )


def _store_rank(store: Mapping[str, Any], reference: str, canonical_code: str | None) -> tuple[bool, bool, bool, bool, str]:
    store_code = str(store.get("store_code", "") or "").strip().upper()
    inferred_code = infer_canonical_store_code_from_document(store)
    return (
        bool(canonical_code and store_code == canonical_code),
        _field_exact_match(store, reference),
        bool(canonical_code and inferred_code == canonical_code),
        bool(store.get("is_active", True)),
        _store_timestamp_key(store),
    )


def resolve_firestore_store_document(reference: str | UUID | None) -> dict[str, Any] | None:
    if reference is None:
        return None
    reference_str = str(reference).strip()
    if not reference_str:
        return None

    try:
        store_id = UUID(reference_str)
    except ValueError:
        store_id = None
    if store_id is not None:
        direct = get_document("stores", str(store_id))
        if direct is not None:
            return direct

    all_stores = query_collection("stores")
    if not all_stores:
        return None

    normalized_reference = reference_str.upper()
    exact_code_matches = [
        store
        for store in all_stores
        if str(store.get("store_code", "") or "").strip().upper() == normalized_reference
    ]
    if exact_code_matches:
        return max(exact_code_matches, key=lambda store: _store_rank(store, reference_str, normalized_reference))

    canonical_code = canonical_store_code_for_value(reference_str)
    exact_field_matches = [
        store for store in all_stores if _field_exact_match(store, reference_str)
    ]
    if exact_field_matches:
        return max(
            exact_field_matches,
            key=lambda store: _store_rank(store, reference_str, canonical_code),
        )

    if canonical_code:
        canonical_matches = [
            store
            for store in all_stores
            if infer_canonical_store_code_from_document(store) == canonical_code
        ]
        if canonical_matches:
            return max(
                canonical_matches,
                key=lambda store: _store_rank(store, reference_str, canonical_code),
            )

    return None
