"""Internal SKU code generation.

Our internal SKU code is independent of supplier codes — similar to Amazon ASIN
or Google product IDs: structured, unique, parseable.

Format: ``{L1}-{L2}-{SEQ6}`` (14 chars, fits varchar(32)).

* ``L1`` — category family (3 chars): DEC, VAS, TRY, WAL, CUS, JWL, MAT, ACC…
* ``L2`` — material / sub-type (3 chars): CPR, CRY, MAR, MAL, BRS, MIX, GEN…
* ``SEQ6`` — 6-digit zero-padded counter per (L1, L2) pair.

Examples:
  ``DEC-CRY-000001`` — Decoration, Crystal, #1
  ``VAS-MAR-000012`` — Vase, Marble, #12
  ``WAL-MIX-000003`` — Wall Art, Mixed, #3

The generator queries the current max sequence for a prefix and increments.
For bulk loads, pass a seeded ``counters`` dict to avoid per-insert roundtrips.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import SKU


# --------------------------------------------------------------------- #
# Category → L1 code mapping                                            #
# --------------------------------------------------------------------- #

# Category description (case-insensitive substring) → L1 prefix
L1_MAP: list[tuple[str, str]] = [
    ("decoration", "DEC"),
    ("摆件", "DEC"),
    ("vase", "VAS"),
    ("花瓶", "VAS"),
    ("tray", "TRY"),
    ("box", "TRY"),
    ("托盘", "TRY"),
    ("盒子", "TRY"),
    ("wall art", "WAL"),
    ("挂画", "WAL"),
    ("hanging", "WAL"),
    ("挂饰", "WAL"),
    ("custom", "CUS"),
    ("可订做", "CUS"),
    ("copper & crystal", "DEC"),  # decorative objects
    ("copper", "DEC"),
    ("crystal", "DEC"),
    ("jewelry", "JWL"),
    ("jewellery", "JWL"),
    ("material", "MAT"),
    ("packaging", "ACC"),
    ("accessor", "ACC"),
]

# Material keyword (case-insensitive) → L2 prefix
L2_MAP: list[tuple[str, str]] = [
    ("crystal", "CRY"),
    ("水晶", "CRY"),
    ("copper", "CPR"),
    ("铜", "CPR"),
    ("brass", "BRS"),
    ("marble", "MAR"),
    ("石", "MAR"),
    ("stone", "MAR"),
    ("malachite", "MAL"),
    ("孔雀", "MAL"),
    ("gold", "GLD"),
    ("silver", "SLV"),
    ("wood", "WOD"),
    ("木", "WOD"),
    ("ceramic", "CER"),
    ("porcelain", "CER"),
    ("resin", "RES"),
    ("glass", "GLS"),
    ("leather", "LTH"),
]

DEFAULT_L1 = "GEN"
DEFAULT_L2 = "MIX"


def classify_l1(category_description: Optional[str]) -> str:
    if not category_description:
        return DEFAULT_L1
    text = category_description.lower()
    for keyword, code in L1_MAP:
        if keyword in text:
            return code
    return DEFAULT_L1


def classify_l2(material_or_description: Optional[str]) -> str:
    """Pick the most prominent material token from a free-form string.

    If multiple materials appear (e.g. "copper + marble"), the first match in
    L2_MAP wins — intentionally biased toward ``CRY``/``CPR`` since they are
    the headline materials in Hengwei's catalogue.
    """
    if not material_or_description:
        return DEFAULT_L2
    text = material_or_description.lower()
    for keyword, code in L2_MAP:
        if keyword in text:
            return code
    return DEFAULT_L2


# --------------------------------------------------------------------- #
# Sequence generation                                                   #
# --------------------------------------------------------------------- #

_PREFIX_RE = re.compile(r"^([A-Z]{3})-([A-Z]{3})-(\d{6})$")


async def next_seq(session: AsyncSession, l1: str, l2: str) -> int:
    """Return the next sequence number for a ``{L1}-{L2}`` prefix."""
    prefix = f"{l1}-{l2}-"
    result = await session.execute(
        select(func.max(SKU.sku_code)).where(SKU.sku_code.like(f"{prefix}%"))
    )
    current_max = result.scalar_one_or_none()
    if not current_max:
        return 1
    m = _PREFIX_RE.match(current_max)
    return int(m.group(3)) + 1 if m else 1


async def generate_code(
    session: AsyncSession,
    *,
    category_description: Optional[str],
    material_hint: Optional[str] = None,
    counters: Optional[dict[tuple[str, str], int]] = None,
) -> str:
    """Generate a new internal SKU code.

    ``counters`` (optional): in-memory dict of ``(l1, l2) -> last_used_seq``,
    used for bulk loads to skip per-row DB lookups. Caller must seed this from
    ``seed_counters_from_db()`` before the first call.
    """
    l1 = classify_l1(category_description)
    l2 = classify_l2(material_hint or category_description)

    if counters is not None:
        key = (l1, l2)
        if key not in counters:
            counters[key] = await next_seq(session, l1, l2) - 1
        counters[key] += 1
        seq = counters[key]
    else:
        seq = await next_seq(session, l1, l2)

    return f"{l1}-{l2}-{seq:06d}"


async def seed_counters_from_db(session: AsyncSession) -> dict[tuple[str, str], int]:
    """Scan existing SKUs and return current max sequence per ``(L1, L2)``."""
    counters: dict[tuple[str, str], int] = {}
    result = await session.execute(select(SKU.sku_code))
    for (code,) in result.all():
        m = _PREFIX_RE.match(code or "")
        if not m:
            continue
        key = (m.group(1), m.group(2))
        seq = int(m.group(3))
        if seq > counters.get(key, 0):
            counters[key] = seq
    return counters
