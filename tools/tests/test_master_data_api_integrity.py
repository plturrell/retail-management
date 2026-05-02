from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import master_data_api as api  # noqa: E402


def _write_master(path: Path, products: list[dict]) -> None:
    path.write_text(
        json.dumps({"metadata": {"last_modified": "test"}, "products": products}),
        encoding="utf-8",
    )


def _product(
    *,
    sku_code: str,
    nec_plu: str,
    description: str,
    stocking_location: str = "jewel",
) -> dict:
    return {
        "sku_code": sku_code,
        "nec_plu": nec_plu,
        "description": description,
        "product_type": "Bowl",
        "material": "Amethyst",
        "stocking_location": stocking_location,
        "inventory_type": "purchased",
        "sources": ["cn-001_invoice_test"],
        "source_orders": ["PO-1"],
    }


@pytest.fixture
def master_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "master_product_list.json"
    monkeypatch.setattr(api, "MASTER_JSON", path)
    return path


def test_create_product_rejects_duplicate_description(master_json: Path) -> None:
    _write_master(
        master_json,
        [
            _product(
                sku_code="VEBWLAMET0000001",
                nec_plu="20000011",
                description="Amethyst Bowl",
            )
        ],
    )

    req = api.ManualProductCreateRequest(
        description="  Amethyst   Bowl  ",
        product_type="Bowl",
        material="Amethyst",
        sourcing_strategy="manufactured_in_house",
    )

    with pytest.raises(HTTPException) as exc:
        api.create_product(req)

    assert exc.value.status_code == 409
    assert "description already exists" in str(exc.value.detail)


def test_patch_product_rejects_duplicate_description(master_json: Path) -> None:
    _write_master(
        master_json,
        [
            _product(sku_code="SKU-1", nec_plu="20000011", description="First Item"),
            _product(sku_code="SKU-2", nec_plu="20000028", description="Second Item"),
        ],
    )

    with pytest.raises(HTTPException) as exc:
        api.patch_product("SKU-2", api.ProductPatch(description=" first item "))

    assert exc.value.status_code == 409
    assert "SKU-1" in str(exc.value.detail)


def test_patch_product_normalises_canonical_location_combo(master_json: Path) -> None:
    _write_master(
        master_json,
        [
            _product(sku_code="SKU-1", nec_plu="20000011", description="First Item"),
        ],
    )

    result = api.patch_product(
        "SKU-1",
        api.ProductPatch(stocking_location="Breeze by East + Jewel Changi"),
    )

    assert result["stocking_location"] == "breeze+jewel"


def test_archive_product_soft_deletes_without_reusing_identity(master_json: Path) -> None:
    _write_master(
        master_json,
        [
            _product(
                sku_code="VEBWLAMET0000001",
                nec_plu="20000011",
                description="First Item",
            ),
        ],
    )

    archived = api.archive_product(
        "VEBWLAMET0000001",
        api.ProductArchiveRequest(reason="Duplicate physical entry"),
        archived_by="owner@example.com",
    )

    assert archived["status"] == "archived"
    assert archived["sale_ready"] is False
    assert archived["block_sales"] is True
    assert archived["use_stock"] is False
    assert archived["archived_by"] == "owner@example.com"
    assert archived["archived_reason"] == "Duplicate physical entry"

    with pytest.raises(HTTPException) as exc:
        api.create_product(
            api.ManualProductCreateRequest(
                description="First Item",
                product_type="Bowl",
                material="Amethyst",
                sourcing_strategy="manufactured_in_house",
            )
        )
    assert exc.value.status_code == 409


def test_restore_product_marks_row_active_but_needs_review(master_json: Path) -> None:
    _write_master(
        master_json,
        [
            {
                **_product(
                    sku_code="VEBWLAMET0000001",
                    nec_plu="20000011",
                    description="First Item",
                ),
                "status": "archived",
                "sale_ready": False,
                "block_sales": True,
                "use_stock": False,
                "previous_use_stock": True,
            },
        ],
    )

    restored = api.restore_product("VEBWLAMET0000001", restored_by="owner@example.com")

    assert restored["status"] == "active"
    assert restored["block_sales"] is False
    assert restored["use_stock"] is True
    assert restored["sale_ready"] is False
    assert restored["needs_review"] is True
    assert restored["restored_by"] == "owner@example.com"


def test_patch_product_rejects_archived_rows(master_json: Path) -> None:
    _write_master(
        master_json,
        [
            {
                **_product(
                    sku_code="SKU-ARCHIVED",
                    nec_plu="20000011",
                    description="Archived Item",
                ),
                "status": "archived",
            },
        ],
    )

    with pytest.raises(HTTPException) as exc:
        api.patch_product("SKU-ARCHIVED", api.ProductPatch(description="Renamed Item"))

    assert exc.value.status_code == 409
    assert "restore it before editing" in str(exc.value.detail)


def test_restore_product_rejects_duplicate_barcode_corruption(master_json: Path) -> None:
    _write_master(
        master_json,
        [
            _product(
                sku_code="SKU-ACTIVE",
                nec_plu="20000011",
                description="Active Item",
            ),
            {
                **_product(
                    sku_code="SKU-ARCHIVED",
                    nec_plu="20000028",
                    description="Archived Item",
                ),
                "plu_code": "20000011",
                "status": "archived",
            },
        ],
    )

    with pytest.raises(HTTPException) as exc:
        api.restore_product("SKU-ARCHIVED")

    assert exc.value.status_code == 409
    assert "barcode 20000011" in str(exc.value.detail)


def test_create_product_rejects_duplicate_supplier_item_code(master_json: Path) -> None:
    existing = _product(
        sku_code="VEBWLAMET0000001",
        nec_plu="20000011",
        description="Existing Amethyst Bowl",
    )
    existing["supplier_id"] = "CN-001"
    existing["supplier_item_code"] = "A001"
    _write_master(master_json, [existing])

    req = api.ManualProductCreateRequest(
        description="Brand New Amethyst Bowl",
        product_type="Bowl",
        material="Amethyst",
        sourcing_strategy="supplier_premade",
        supplier_id="CN-001",
        supplier_item_code="A001",
        internal_code="A001-NEW",
    )

    with pytest.raises(HTTPException) as exc:
        api.create_product(req)

    assert exc.value.status_code == 409
    assert "supplier_item_code A001" in str(exc.value.detail)
    assert "VEBWLAMET0000001" in str(exc.value.detail)


def test_create_product_allows_same_supplier_item_code_for_different_supplier(
    master_json: Path,
) -> None:
    existing = _product(
        sku_code="VEBWLAMET0000001",
        nec_plu="20000011",
        description="Existing Amethyst Bowl",
    )
    existing["supplier_id"] = "CN-001"
    existing["supplier_item_code"] = "A001"
    _write_master(master_json, [existing])

    req = api.ManualProductCreateRequest(
        description="Different Supplier Same Code",
        product_type="Bowl",
        material="Amethyst",
        sourcing_strategy="supplier_premade",
        supplier_id="CN-002",
        supplier_item_code="A001",
        internal_code="A001-CN002",
    )

    result = api.create_product(req)
    assert result["supplier_id"] == "CN-002"
    assert result["supplier_item_code"] == "A001"


def test_manual_product_create_request_rejects_invalid_cost_currency() -> None:
    with pytest.raises(ValidationError):
        api.ManualProductCreateRequest(
            description="Test Item",
            product_type="Bowl",
            material="Amethyst",
            cost_currency="USDS",
        )


def test_manual_product_create_request_normalises_cost_currency_case() -> None:
    req = api.ManualProductCreateRequest(
        description="Test Item",
        product_type="Bowl",
        material="Amethyst",
        cost_currency="  usd ",
    )
    assert req.cost_currency == "USD"
