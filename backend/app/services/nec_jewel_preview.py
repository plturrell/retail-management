"""Pre-flight validator for the CAG / NEC Jewel POS master bundle.

Runs the same data fetch as the real exporter but, instead of producing
files, returns a structured report so operators can fix problems before
burning an SFTP slot. Hard-errors mirror the spec validations baked into
``nec_jewel_txt`` (max-length truncation, mandatory fields, valid TAX_CODE,
INVDETAILS action, etc.); soft warnings surface drift between our master
data and what NEC will accept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from app.services import nec_jewel_export as legacy
from app.services import nec_jewel_txt as nx


@dataclass
class PreviewIssue:
    sku_code: str
    field: str
    severity: str  # "error" | "warning"
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku_code": self.sku_code,
            "field": self.field,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class PreviewResult:
    sellable_count: int = 0
    excluded_count: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    issues: list[PreviewIssue] = field(default_factory=list)
    excluded_summary: dict[str, int] = field(default_factory=dict)
    tenant_code: str = ""
    nec_store_id: str = ""
    taxable: bool = True

    @property
    def errors(self) -> list[PreviewIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[PreviewIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def is_ready(self) -> bool:
        return self.sellable_count > 0 and not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "sellable_count": self.sellable_count,
            "excluded_count": self.excluded_count,
            "counts": dict(self.counts),
            "tenant_code": self.tenant_code,
            "nec_store_id": self.nec_store_id,
            "taxable": self.taxable,
            "is_ready": self.is_ready,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "excluded_summary": dict(self.excluded_summary),
        }


# Spec-derived limits live in app.constants.nec_limits — re-exported here so
# call sites in this module read like before. See that file for the source
# (vendor "Catalog import — fixed columns" PDF).
from app.constants.nec_limits import (  # noqa: E402
    MAX_BRAND,
    MAX_PLU_CODE,
    MAX_SKU_CODE,
    MAX_SKU_DESC,
    VALID_AGE_GROUPS,
    VALID_GENDERS,
)


def _validate_sku(product: Mapping[str, Any], *, taxable: bool) -> list[PreviewIssue]:
    sku = str(product.get("sku_code") or "")
    issues: list[PreviewIssue] = []
    if not sku:
        issues.append(PreviewIssue("(missing)", "sku_code", "error", "SKU code is empty"))
        return issues
    if len(sku) > MAX_SKU_CODE:
        issues.append(
            PreviewIssue(sku, "sku_code", "error", f"SKU code exceeds {MAX_SKU_CODE} chars (got {len(sku)})")
        )
    desc = str(product.get("description") or "")
    if not desc:
        issues.append(PreviewIssue(sku, "description", "error", "Description is required"))
    elif len(desc) > MAX_SKU_DESC:
        issues.append(
            PreviewIssue(sku, "description", "warning", f"Description >60 chars; will be truncated (got {len(desc)})")
        )
    brand = product.get("brand_name") or legacy.BRAND_NAME
    if not brand:
        issues.append(PreviewIssue(sku, "brand_name", "error", "ITEM_ATTRIB1 (brand) is mandatory"))
    elif len(str(brand)) > MAX_BRAND:
        issues.append(
            PreviewIssue(sku, "brand_name", "warning", "Brand >20 chars; will be truncated")
        )
    age = str(product.get("age_group") or "ADULT").upper()
    if age not in VALID_AGE_GROUPS:
        issues.append(
            PreviewIssue(
                sku, "age_group", "error",
                f"ITEM_ATTRIB3 must be one of {sorted(VALID_AGE_GROUPS)}; got {age!r}",
            )
        )
    gender = str(product.get("gender") or "").upper()
    if gender and gender not in VALID_GENDERS:
        issues.append(
            PreviewIssue(
                sku, "gender", "warning",
                f"ITEM_ATTRIB2 should be MALE/FEMALE/UNISEX; got {gender!r}",
            )
        )
    cost = product.get("cost_price")
    if cost is None:
        issues.append(PreviewIssue(sku, "cost_price", "warning", "Cost price not set (COSTPRICE will default to 0)"))
    return issues


def _validate_price(product: Mapping[str, Any], *, taxable: bool) -> list[PreviewIssue]:
    sku = str(product.get("sku_code") or "")
    issues: list[PreviewIssue] = []
    incl = product.get("retail_price") or product.get("price_incl_tax")
    if incl is None:
        issues.append(PreviewIssue(sku, "retail_price", "error", "PRICE row will be omitted (no active retail price)"))
        return issues
    try:
        incl_f = float(incl)
    except (TypeError, ValueError):
        issues.append(PreviewIssue(sku, "retail_price", "error", f"Invalid retail price {incl!r}"))
        return issues
    if incl_f < 0:
        issues.append(PreviewIssue(sku, "retail_price", "error", f"Negative price {incl_f}"))
    excl = product.get("price_excl_tax")
    if excl is not None:
        try:
            excl_f = float(excl)
        except (TypeError, ValueError):
            issues.append(PreviewIssue(sku, "price_excl_tax", "error", f"Invalid excl-tax price {excl!r}"))
            return issues
        if taxable:
            ratio = (incl_f / excl_f) if excl_f else 0
            # Spec section 4.4 example: tolerance ~0.16 between calc and supplied ratio.
            calc_ratio = 1 + nx.GST_RATE_DEFAULT
            if abs(ratio - calc_ratio) > 0.05:
                issues.append(
                    PreviewIssue(
                        sku, "price_excl_tax", "warning",
                        f"Inclusive/exclusive ratio {ratio:.3f} drifts from {calc_ratio:.3f} (GST 9%)",
                    )
                )
        else:
            if abs(incl_f - excl_f) > 0.01:
                issues.append(
                    PreviewIssue(
                        sku, "price_excl_tax", "warning",
                        "Airside store: incl-tax price should equal excl-tax price",
                    )
                )
    return issues


def _validate_plu(product: Mapping[str, Any]) -> list[PreviewIssue]:
    sku = str(product.get("sku_code") or "")
    plu = product.get("nec_plu") or product.get("plu_code")
    if not plu:
        return [PreviewIssue(sku, "nec_plu", "warning", "PLU row will be omitted (no barcode assigned)")]
    if len(str(plu)) > MAX_PLU_CODE:
        return [PreviewIssue(sku, "nec_plu", "error", f"PLU code exceeds {MAX_PLU_CODE} chars")]
    return []


def _summarise_excluded(excluded: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {
        "not_sale_ready": 0,
        "no_active_price": 0,
        "no_plu": 0,
        "no_description": 0,
        "blocked": 0,
    }
    for row in excluded:
        if not row.get("sale_ready"):
            summary["not_sale_ready"] += 1
        if row.get("status") != "active" or row.get("block_sales"):
            summary["blocked"] += 1
        if not row.get("has_price"):
            summary["no_active_price"] += 1
        if not row.get("has_plu"):
            summary["no_plu"] += 1
        if not row.get("description"):
            summary["no_description"] += 1
    return {k: v for k, v in summary.items() if v}


def build_preview(
    products: list[Mapping[str, Any]],
    excluded: list[Mapping[str, Any]],
    *,
    tenant_code: str,
    nec_store_id: str,
    taxable: bool,
) -> PreviewResult:
    """Run validation across the sellable list and compile counts.

    ``products`` and ``excluded`` are the two lists returned by
    :func:`app.services.nec_jewel_export.fetch_sellable_skus_from_firestore`.
    """
    counts = {
        "catg": 0,
        "sku": 0,
        "plu": 0,
        "price": 0,
        "invdetails": 0,
        "promo": 0,
    }
    issues: list[PreviewIssue] = []

    # CATG count is fixed by the tenant tree (independent of products).
    counts["catg"] = len(legacy.make_tenant_catg_tree(tenant_code))

    seen_sku_codes: set[str] = set()
    for p in products:
        sku = str(p.get("sku_code") or "")
        # Cheap duplicate detection (spec rule: SKU_CODE unique within file).
        if sku in seen_sku_codes:
            issues.append(PreviewIssue(sku, "sku_code", "error", "Duplicate SKU code in export set"))
        elif sku:
            seen_sku_codes.add(sku)
        sku_issues = _validate_sku(p, taxable=taxable)
        plu_issues = _validate_plu(p)
        price_issues = _validate_price(p, taxable=taxable)
        issues.extend(sku_issues + plu_issues + price_issues)

        # Counts mirror what the bundle builder will emit.
        if sku and p.get("description"):
            counts["sku"] += 1
        if p.get("nec_plu") or p.get("plu_code"):
            counts["plu"] += 1
        if p.get("retail_price") or p.get("price_incl_tax"):
            counts["price"] += 1
        qty = p.get("qty_on_hand")
        try:
            if qty is not None and int(qty) > 0:
                counts["invdetails"] += 1
        except (TypeError, ValueError):
            pass
        counts["promo"] += len(legacy.PROMO_TIERS) if sku else 0

    return PreviewResult(
        sellable_count=len(products),
        excluded_count=len(excluded),
        counts=counts,
        issues=issues,
        excluded_summary=_summarise_excluded(excluded),
        tenant_code=tenant_code,
        nec_store_id=nec_store_id,
        taxable=taxable,
    )


__all__ = ["PreviewIssue", "PreviewResult", "build_preview"]
