from __future__ import annotations

import pytest

from app.services.store_identity import (
    canonical_store_code_for_value,
    canonicalize_store_code_input,
    infer_canonical_store_code_from_document,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("breeze", "BREEZE-01"),
        ("Breeze by East", "BREEZE-01"),
        ("jewel", "JEWEL-01"),
        ("JEWEL-B1-241", "JEWEL-01"),
        ("takashimaya", "TAKA-01"),
        ("taka", "TAKA-01"),
        ("isetan scotts", "ISETAN-01"),
        ("online", "ONLINE-01"),
        ("shopify", "ONLINE-01"),
    ],
)
def test_canonical_store_code_for_value(value: str, expected: str) -> None:
    assert canonical_store_code_for_value(value) == expected


def test_canonicalize_store_code_input_preserves_unknown_codes() -> None:
    assert canonicalize_store_code_input("custom-99") == "CUSTOM-99"
    assert canonicalize_store_code_input("unknown place") == "unknown place"


def test_infer_canonical_store_code_from_document_uses_store_fields() -> None:
    store_doc = {
        "store_code": "JEWEL-01",
        "name": "VictoriaEnso - Jewel Changi",
        "location": "Jewel Changi Airport",
        "address": "78 Airport Blvd",
    }
    assert infer_canonical_store_code_from_document(store_doc) == "JEWEL-01"


def test_infer_canonical_store_code_from_document_supports_online() -> None:
    store_doc = {
        "name": "VictoriaEnso - Online",
        "location": "Website",
    }
    assert infer_canonical_store_code_from_document(store_doc) == "ONLINE-01"
