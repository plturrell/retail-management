"""High-level orchestration: build the full NEC master-file bundle.

Combines the existing Firestore fetcher in :mod:`app.services.nec_jewel_export`
with the spec-compliant TXT writers in :mod:`app.services.nec_jewel_txt` so
that one call produces every artefact a tenant needs to drop into
``Inbound/Working/<tenant>/`` (per the SFTP onboarding guide):

    - ``CATG_<tenant>_<ts>.txt``       (mandatory)
    - ``SKU_<storeID>_<ts>.txt``       (mandatory)
    - ``PLU_<tenant>_<ts>.txt``        (optional)
    - ``PRICE_<tenant>_<ts>.txt``      (mandatory)
    - ``INVDETAILS_<storeID>_<ts>.txt``(optional)
    - ``PROMO_<tenant>_<ts>.txt``      (optional)

The Excel workbook produced by ``nec_jewel_export.build_workbook`` remains
the canonical operator-facing artefact; this bundle is for the SFTP
upload path.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from app.services import nec_jewel_export as legacy
from app.services import nec_jewel_txt as nx


@dataclass
class BundleResult:
    files: dict[str, bytes] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)
    tenant_code: str = ""
    store_id: str = ""

    def total_bytes(self) -> int:
        return sum(len(v) for v in self.files.values())

    def as_zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, payload in self.files.items():
                zf.writestr(name, payload)
        return buf.getvalue()


def _build_catg_rows(tenant_code: str) -> list[tuple[str, str, str, str]]:
    return [
        (parent, child, desc, cag or "")
        for parent, child, desc, cag in legacy.make_tenant_catg_tree(tenant_code)
    ]


def _resolve_tenant_catg_code(form_factor: str) -> str:
    cag = legacy.CAG_CATG_MAP.get(form_factor, "DECORATIVE ITEM")
    return legacy._CAG_TO_TENANT.get(cag, "VE_HD_DECOR")


def build_master_bundle(
    products: Iterable[Mapping[str, Any]],
    *,
    tenant_code: str,
    store_id: str,
    taxable: bool = True,
    gst_rate: float = nx.GST_RATE_DEFAULT,
    promo_tiers: Iterable[tuple[str, str, float]] | None = None,
    now: datetime | None = None,
    include_inventory: bool = True,
    include_promo: bool = True,
) -> BundleResult:
    """Build the full TXT bundle for one tenant + store.

    ``products`` should contain the dict shape returned by
    :func:`app.services.nec_jewel_export.fetch_sellable_skus_from_firestore`
    (sku_code, description, cost_price, retail_price, price_excl_tax,
    qty_on_hand, nec_plu, attributes, …).
    """
    products = list(products)
    now = now or datetime.now()
    tax_code = "G" if taxable else "N"
    promo_tiers = list(promo_tiers or legacy.PROMO_TIERS)

    files: dict[str, bytes] = {}
    counts: dict[str, int] = {}

    # CATG
    catg_rows = _build_catg_rows(tenant_code)
    files[nx.filename_catg(tenant_code, now)] = nx.write_catg(catg_rows).encode("ascii")
    counts["catg"] = len(catg_rows)

    # SKU
    sku_rows: list[list[Any]] = []
    for product in products:
        sku_code = product.get("sku_code")
        desc = product.get("description")
        if not sku_code or not desc:
            continue
        attrs = product.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                import json
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        material = (attrs.get("materials") or attrs.get("material") or product.get("material") or "")
        sku_rows.append(
            nx.sku_row(
                mode="A",
                sku_code=str(sku_code),
                sku_desc=str(desc),
                cost_price=product.get("cost_price"),
                sku_catg_tenant=_resolve_tenant_catg_code(
                    product.get("form_factor") or product.get("product_type") or ""
                ),
                tax_code=tax_code,
                item_attrib1_brand=str(product.get("brand_name") or legacy.BRAND_NAME),
                item_attrib2_gender=str(product.get("gender") or "UNISEX"),
                item_attrib3_age_group=str(product.get("age_group") or "ADULT"),
                item_attrib4_changi_collection="NA",
                use_stock=bool(product.get("use_stock", True)),
                block_sales=bool(product.get("block_sales", False)),
                sku_long_desc=str(product.get("long_description") or product.get("description") or ""),
                search_name=str(material)[:20] if material else "",
            )
        )
    files[nx.filename_sku(store_id, now)] = nx.write_sku(sku_rows).encode("ascii", errors="replace")
    counts["sku"] = len(sku_rows)

    # PLU
    plu_rows: list[list[Any]] = []
    for product in products:
        plu = product.get("nec_plu") or product.get("plu_code")
        sku = product.get("sku_code")
        if not plu or not sku:
            continue
        plu_rows.append(nx.plu_row(mode="A", plu_code=str(plu), sku_code=str(sku)))
    files[nx.filename_plu(tenant_code, now)] = nx.write_plu(plu_rows).encode("ascii")
    counts["plu"] = len(plu_rows)

    # PRICE
    price_rows: list[list[Any]] = []
    today_str = now.strftime("%Y%m%d")
    for product in products:
        price_incl = product.get("retail_price") or product.get("price_incl_tax")
        sku = product.get("sku_code")
        if not price_incl or not sku:
            continue
        try:
            price_incl_f = float(price_incl)
        except (TypeError, ValueError):
            continue
        price_excl = product.get("price_excl_tax")
        if price_excl is None:
            price_excl_f = nx.derive_excl_tax(price_incl_f, taxable=taxable, gst_rate=gst_rate)
        else:
            try:
                price_excl_f = float(price_excl)
            except (TypeError, ValueError):
                price_excl_f = nx.derive_excl_tax(price_incl_f, taxable=taxable, gst_rate=gst_rate)
        price_rows.append(
            nx.price_row(
                mode="A",
                sku_code=str(sku),
                price_incl_tax=price_incl_f,
                price_excl_tax=price_excl_f,
                price_frdate=today_str,
                price_todate=nx.FAR_FUTURE_DATE,
            )
        )
    files[nx.filename_price(tenant_code, now)] = nx.write_price(price_rows).encode("ascii")
    counts["price"] = len(price_rows)

    # INVDETAILS (optional)
    if include_inventory:
        inv_rows: list[list[Any]] = []
        for product in products:
            qty = product.get("qty_on_hand")
            sku = product.get("sku_code")
            if not sku or qty is None:
                continue
            try:
                qty_int = int(qty)
            except (TypeError, ValueError):
                continue
            if qty_int <= 0:
                continue
            inv_rows.append(nx.invdetails_row(sku_code=str(sku), action="Update", inv_value=qty_int))
        files[nx.filename_invdetails(store_id, now)] = nx.write_invdetails(inv_rows).encode("ascii")
        counts["invdetails"] = len(inv_rows)

    # PROMO (optional, depends on Discount Headers pre-existing in D365FO)
    if include_promo and promo_tiers:
        promo_rows: list[list[Any]] = []
        for disc_id, _label, pct in promo_tiers:
            for product in products:
                sku = product.get("sku_code")
                if not sku:
                    continue
                promo_rows.append(
                    nx.promo_row(
                        disc_id=disc_id,
                        sku_code=str(sku),
                        line_type="Include",
                        disc_method="PercentOff",
                        disc_value=float(pct),
                    )
                )
        files[nx.filename_promo(tenant_code, now)] = nx.write_promo(promo_rows).encode("ascii")
        counts["promo"] = len(promo_rows)

    return BundleResult(
        files=files,
        counts=counts,
        generated_at=now,
        tenant_code=tenant_code,
        store_id=store_id,
    )


__all__ = ["BundleResult", "build_master_bundle"]
