"""Spec-compliant TXT writers for the CAG / NEC Jewel POS master interfaces.

Reference: ``CAG-Jewel-ISD-Interfaces TXT Formats v1.7.6j.pdf``
(see ``docs/CAG - NEC Retail POS Onboarding Guides``).

The Excel workbook (``nec_jewel_export.py``) remains the human-facing
artefact. These writers emit the actual ``.txt`` files that get dropped
into the SFTP ``Inbound/Working/<tenant>/`` folder.

General rules implemented here (per spec sections 2 and 5.3):

- ASCII, comma-delimited, CRLF terminator, **no header row**.
- Fields containing ``,`` or ``"`` are wrapped in double quotes; embedded
  ``"`` is doubled (rules 3 and 4). Per rule 11 we also expose
  :func:`sanitize_field` so callers can strip these characters upstream
  if D365FO has rejected quoted variants for a given tenant.
- Mandatory char fields use ``"NA"``; mandatory numeric fields use
  ``"0"`` (rule 10).
- Dates use ``YYYYMMDD``; the never-expires sentinel is ``20991231``.

Filenames (sections 4.1-4.6):

================ ===========================================
Interface        Filename pattern
================ ===========================================
CATG             ``CATG_<tenant>_<YYYYMMDDHHMMSS>.txt``
SKU              ``SKU_<storeID>_<YYYYMMDDHHMMSS>.txt``
PLU              ``PLU_<tenant>_<YYYYMMDDHHMMSS>.txt``
PRICE            ``PRICE_<tenant>_<YYYYMMDDHHMMSS>.txt``
INVDETAILS       ``INVDETAILS_<storeID>_<YYYYMMDDHHMMSS>.txt``
PROMO            ``PROMO_<tenant>_<YYYYMMDDHHMMSS>.txt``
================ ===========================================
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Sequence

# Spec sentinels.
NA_CHAR = "NA"
NA_NUMERIC = "0"
FAR_FUTURE_DATE = "20991231"
RECORD_TERMINATOR = "\r\n"
GST_RATE_DEFAULT = 0.09  # SG GST 9% (FY2024+); override per call if needed.

# Valid INVDETAILS actions per spec section 4.5.
INV_ACTIONS = ("Add", "Subtract", "Update")

# Valid SKU MODE values per spec section 4.2.
SKU_MODES = ("F", "A", "E", "D")

# Valid PLU / PRICE / PROMO MODE values.
PLU_MODES = ("A", "E", "D")
PRICE_MODES = ("A", "D")


# ---------------------------------------------------------------------------
# Field encoding helpers
# ---------------------------------------------------------------------------

def sanitize_field(value: Any) -> str:
    """Strip the two characters that MUST NOT appear inside a TXT field.

    Per spec rule 11, fields cannot contain ``"`` or ``,``. We replace
    ``"`` with ``''`` and ``,`` with ``;`` so that downstream operators
    don't have to deal with quoted variants. Callers can opt out by
    formatting fields directly with :func:`format_field`.
    """
    s = "" if value is None else str(value)
    return s.replace('"', "''").replace(",", ";")


def format_field(value: Any) -> str:
    """Encode a single field per spec rules 3-5.

    - ``None`` → empty (caller decides if mandatory; use NA_CHAR / "0" instead).
    - Numeric types render without thousand separators.
    - Strings containing ``,`` or ``"`` are double-quote-wrapped with
      embedded ``"`` doubled.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        # Spec example uses "9842.23"; never force trailing zeroes.
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".") if "." in f"{value}" else str(value)
    s = str(value)
    if "," in s or '"' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def format_money(value: Any) -> str:
    """Format a monetary amount as ``Numeric(20,2)`` per spec."""
    if value is None or value == "":
        return "0.00"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def format_row(fields: Sequence[Any]) -> str:
    """Join encoded fields with ``,`` and append CRLF."""
    return ",".join(format_field(f) for f in fields) + RECORD_TERMINATOR


# ---------------------------------------------------------------------------
# Filenames
# ---------------------------------------------------------------------------

def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d%H%M%S")


def filename_catg(tenant: str, now: datetime | None = None) -> str:
    return f"CATG_{tenant}_{_timestamp(now)}.txt"


def filename_sku(store_id: str, now: datetime | None = None) -> str:
    return f"SKU_{store_id}_{_timestamp(now)}.txt"


def filename_plu(tenant: str, now: datetime | None = None) -> str:
    return f"PLU_{tenant}_{_timestamp(now)}.txt"


def filename_price(tenant: str, now: datetime | None = None) -> str:
    return f"PRICE_{tenant}_{_timestamp(now)}.txt"


def filename_invdetails(store_id: str, now: datetime | None = None) -> str:
    return f"INVDETAILS_{store_id}_{_timestamp(now)}.txt"


def filename_promo(tenant: str, now: datetime | None = None) -> str:
    return f"PROMO_{tenant}_{_timestamp(now)}.txt"


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_catg(rows: Iterable[Sequence[Any]]) -> str:
    """CATG file (section 4.1).

    ``rows`` yields ``(parent_catg, child_catg, child_desc, cag_catg)``.
    ``cag_catg`` may be empty for non-leaf nodes per the sample.
    """
    out: list[str] = []
    for row in rows:
        if len(row) != 4:
            raise ValueError(f"CATG row must have 4 fields, got {len(row)}: {row!r}")
        parent, child, desc, cag = row
        if not parent or not child or not desc:
            raise ValueError(f"CATG mandatory field missing in row: {row!r}")
        out.append(format_row([parent, child, desc, cag or ""]))
    return "".join(out)


def _coerce_yn(value: Any, *, default: str = "N") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "Y" if value else "N"
    s = str(value).strip().upper()
    if s in ("Y", "YES", "TRUE", "1"):
        return "Y"
    if s in ("N", "NO", "FALSE", "0", ""):
        return "N"
    return default


def sku_row(
    *,
    mode: str,
    sku_code: str,
    sku_desc: str,
    cost_price: float | None,
    sku_catg_tenant: str,
    tax_code: str,
    item_attrib1_brand: str,
    item_attrib3_age_group: str = "ALL",
    item_attrib4_changi_collection: str = "NA",
    use_stock: bool | str = True,
    block_sales: bool | str = False,
    open_item: bool | str = False,
    sku_disc: bool | str = True,
    sku_long_desc: str = "",
    item_attrib2_gender: str = "",
    item_attrib5_brand_collection: str = "",
    item_attrib6_language: str = "",
    item_attrib7_genre: str = "",
    item_attrib8_geography: str = "",
    rental_dept: str = "",
    zero_price_valid: bool | str = False,
    search_name: str = "",
    enable_uniqueid: bool | str = False,
) -> list[Any]:
    """Build a 50-field SKU row in spec column order (section 4.2)."""
    if mode not in SKU_MODES:
        raise ValueError(f"SKU MODE must be one of {SKU_MODES}, got {mode!r}")
    if tax_code not in ("G", "N"):
        raise ValueError(f"TAX_CODE must be 'G' or 'N', got {tax_code!r}")
    if not sku_code or not sku_desc or not sku_catg_tenant or not item_attrib1_brand:
        raise ValueError("SKU mandatory field missing")
    return [
        "",                                     # 1  FILENAME (NOT USE)
        mode,                                   # 2  MODE
        sku_code[:16],                          # 3  SKU_CODE
        sku_desc[:60],                          # 4  SKU_DESC
        format_money(cost_price) if cost_price is not None else "",  # 5 COSTPRICE
        "",                                     # 6  AVGCOST (NOT USE)
        "",                                     # 7  SKU_PRICE (NOT USE)
        "",                                     # 8  SKU_PRICE1 (NOT USE)
        "",                                     # 9  SKU_EDATE1 (NOT USE)
        "",                                     # 10 SKU_ETIME1 (NOT USE)
        sku_catg_tenant[:20],                   # 11 SKU_CATG_TENANT
        "",                                     # 12 SKU_CATG_CAG (NOT USE)
        "", "", "",                             # 13-15 SKU_ROL/ROQ/QOH (NOT USE)
        tax_code,                               # 16 TAX_CODE
        "", "", "", "", "",                     # 17-21 PRO_* (NOT USE)
        _coerce_yn(open_item),                  # 22 OPEN_ITEM
        "",                                     # 23 KIT (NOT USE)
        "",                                     # 24 REMARKS (NOT USE)
        _coerce_yn(sku_disc, default="Y"),      # 25 SKU_DISC
        "", "", "",                             # 26-28 LALO/HALO/MIN_AGE (NOT USE)
        item_attrib1_brand[:20],                # 29 ITEM_ATTRIB1 (Brand) [M]
        (item_attrib2_gender or "")[:20],       # 30 ITEM_ATTRIB2 (Gender)
        item_attrib3_age_group[:20],            # 31 ITEM_ATTRIB3 (Age group) [M]
        item_attrib4_changi_collection[:20],    # 32 ITEM_ATTRIB4 (Changi coll) [M]
        (rental_dept or "")[:20],               # 33 RENTAL_DEPT
        _coerce_yn(use_stock, default="Y"),     # 34 USE_STOCK
        (sku_long_desc or "")[:1000],           # 35 SKU_LONG_DESC
        _coerce_yn(block_sales),                # 36 BLOCK_SALES
        (item_attrib5_brand_collection or "")[:20],  # 37 ITEM_ATTRIB5
        (item_attrib6_language or "")[:20],     # 38 ITEM_ATTRIB6
        (item_attrib7_genre or "")[:20],        # 39 ITEM_ATTRIB7
        (item_attrib8_geography or "")[:20],    # 40 ITEM_ATTRIB8
        "", "", "", "", "", "", "",             # 41-47 ITEM_ATTRIB9-15 (reserved)
        _coerce_yn(zero_price_valid),           # 48 ZERO_PRICE_VALID
        (search_name or "")[:20],               # 49 SEARCH_NAME
        _coerce_yn(enable_uniqueid),            # 50 ENABLE_UNIQUEID
    ]


def write_sku(rows: Iterable[Sequence[Any]]) -> str:
    """SKU file (section 4.2). ``rows`` are pre-built via :func:`sku_row`."""
    return "".join(format_row(r) for r in rows)


def plu_row(*, mode: str, plu_code: str, sku_code: str) -> list[Any]:
    if mode not in PLU_MODES:
        raise ValueError(f"PLU MODE must be one of {PLU_MODES}, got {mode!r}")
    if not plu_code or not sku_code:
        raise ValueError("PLU mandatory field missing")
    return ["", mode, str(plu_code)[:80], str(sku_code)[:16]]


def write_plu(rows: Iterable[Sequence[Any]]) -> str:
    return "".join(format_row(r) for r in rows)


def price_row(
    *,
    mode: str,
    sku_code: str,
    price_incl_tax: float,
    price_excl_tax: float,
    store_id: str = "",
    price_unit: int = 1,
    price_frdate: str | date,
    price_todate: str | date = FAR_FUTURE_DATE,
) -> list[Any]:
    if mode not in PRICE_MODES:
        raise ValueError(f"PRICE MODE must be one of {PRICE_MODES}, got {mode!r}")
    if not sku_code:
        raise ValueError("PRICE SKU_CODE missing")
    return [
        mode,
        str(sku_code)[:16],
        store_id or "",
        format_money(price_incl_tax),
        format_money(price_excl_tax),
        price_unit if price_unit else "",
        _format_date(price_frdate),
        _format_date(price_todate) or FAR_FUTURE_DATE,
    ]


def write_price(rows: Iterable[Sequence[Any]]) -> str:
    return "".join(format_row(r) for r in rows)


def invdetails_row(*, sku_code: str, action: str, inv_value: int) -> list[Any]:
    if action not in INV_ACTIONS:
        raise ValueError(f"INVDETAILS ACTION must be one of {INV_ACTIONS}, got {action!r}")
    if not sku_code:
        raise ValueError("INVDETAILS SKU_CODE missing")
    if inv_value < 0:
        raise ValueError("INVDETAILS INV_VALUE must be a positive integer")
    return ["", str(sku_code)[:16], action, int(inv_value)]


def write_invdetails(rows: Iterable[Sequence[Any]]) -> str:
    return "".join(format_row(r) for r in rows)


def promo_row(
    *,
    disc_id: str,
    line_type: str,
    disc_method: str,
    disc_value: float,
    sku_code: str = "",
    tenant_catg_code: str = "",
    mm_linegrp: str = "",
) -> list[Any]:
    if line_type not in ("Include", "Exclude"):
        raise ValueError("PROMO LINE_TYPE must be 'Include' or 'Exclude'")
    if disc_method not in ("AmountOff", "PercentOff", "Price", ""):
        raise ValueError("PROMO DISC_METHOD must be AmountOff/PercentOff/Price")
    if not sku_code and not tenant_catg_code:
        raise ValueError("PROMO requires SKU_CODE or TENANT_CATG_CODE")
    return [
        disc_id[:20],
        tenant_catg_code[:20] if tenant_catg_code else "",
        sku_code[:16] if sku_code else "",
        line_type,
        disc_method,
        format_money(disc_value),
        mm_linegrp[:1] if mm_linegrp else "",
    ]


def write_promo(rows: Iterable[Sequence[Any]]) -> str:
    return "".join(format_row(r) for r in rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_date(value: str | date | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    s = str(value).strip()
    if not s:
        return ""
    # Accept already-formatted YYYYMMDD or ISO YYYY-MM-DD.
    if len(s) == 8 and s.isdigit():
        return s
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"Unrecognised date format: {value!r}") from exc


# ---------------------------------------------------------------------------
# Bundle helpers
# ---------------------------------------------------------------------------

def derive_excl_tax(price_incl: float, *, taxable: bool, gst_rate: float = GST_RATE_DEFAULT) -> float:
    """Compute PRICE_EXCLTAX from PRICE_INCLTAX for a taxable store."""
    if not taxable:
        return float(price_incl)
    return round(float(price_incl) / (1 + gst_rate), 2)


def derive_incl_tax(price_excl: float, *, taxable: bool, gst_rate: float = GST_RATE_DEFAULT) -> float:
    if not taxable:
        return float(price_excl)
    return round(float(price_excl) * (1 + gst_rate), 2)


__all__ = [
    "FAR_FUTURE_DATE",
    "GST_RATE_DEFAULT",
    "INV_ACTIONS",
    "PLU_MODES",
    "PRICE_MODES",
    "RECORD_TERMINATOR",
    "SKU_MODES",
    "derive_excl_tax",
    "derive_incl_tax",
    "filename_catg",
    "filename_invdetails",
    "filename_plu",
    "filename_price",
    "filename_promo",
    "filename_sku",
    "format_field",
    "format_money",
    "format_row",
    "invdetails_row",
    "plu_row",
    "price_row",
    "promo_row",
    "sanitize_field",
    "sku_row",
    "write_catg",
    "write_invdetails",
    "write_plu",
    "write_price",
    "write_promo",
    "write_sku",
]
