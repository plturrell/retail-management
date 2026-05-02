"""EAN-8 / NEC-PLU helpers (mirror of ``tools/scripts/identifier_utils``).

Kept as a separate copy inside the backend package so production code does
not depend on the developer ``tools/`` tree being on ``PYTHONPATH``. Do
not edit one without keeping the other in sync.

PLU spec (current)
------------------
NEC POS accepts EAN-8 in-store / restricted-circulation codes. We use::

    PLU = "2" + seq(6 digits) + check(1 digit)   → 8 digits, GTIN-8

The ``2`` prefix is GS1's restricted-circulation marker (not a real GS1
prefix), so codes are unique within the store but not globally registered.
This is by design — it means we don't need a GS1 membership.

The check digit follows GTIN-8 weighting: positions 1,3,5,7 (1-indexed
from the **left**) weighted by 3, positions 2,4,6 weighted by 1.

Legacy EAN-13 helpers
---------------------
The helpers ending in ``_ean13`` exist only so the migration scripts in
``tools/scripts/`` can still read the old 13-digit ``200…`` codes that
were issued before the EAN-8 switch. New PLUs MUST go through
:func:`generate_nec_plu` (EAN-8). Do not call the EAN-13 helpers from
production code that allocates fresh PLUs.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

# ── EAN-8 (current) ──────────────────────────────────────────────────────────

PLU_PREFIX = "2"
PLU_BODY_DIGITS = 7  # 7-digit body before the check digit
PLU_SEQUENCE_DIGITS = 6  # max seq = 999_999
PLU_TOTAL_DIGITS = PLU_BODY_DIGITS + 1  # 8

SKU_SEQUENCE_DIGITS = 7  # SKU still pads to 7 digits even though PLU caps at 6
_SKU_SEQUENCE_RE = re.compile(r"(\d{7})$")

# ── EAN-13 (legacy, for reading pre-switch data) ─────────────────────────────

_LEGACY_PLU_PREFIX = "200"
_LEGACY_PLU_BODY_DIGITS = 12
_LEGACY_PLU_SEQUENCE_DIGITS = 9


# ── EAN-8 primitives ─────────────────────────────────────────────────────────


def compute_ean8_check_digit(code7: str) -> str:
    """Return the GTIN-8 check digit for a 7-digit body string."""
    if len(code7) != PLU_BODY_DIGITS or not code7.isdigit():
        raise ValueError(f"EAN-8 body must be exactly 7 digits, got {code7!r}")
    # positions 1..7 (1-indexed from left): weights 3,1,3,1,3,1,3
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(code7))
    return str((10 - (total % 10)) % 10)


def is_valid_ean8(code: str | None) -> bool:
    if code is None:
        return False
    text = str(code).strip()
    if len(text) != PLU_TOTAL_DIGITS or not text.isdigit():
        return False
    return compute_ean8_check_digit(text[:PLU_BODY_DIGITS]) == text[PLU_BODY_DIGITS]


# Generic alias — what callers should use to ask "is this a current PLU?"
is_valid_plu = is_valid_ean8


def generate_nec_plu(seq: int) -> str:
    """Return the EAN-8 PLU for sequence ``seq`` (1-indexed)."""
    if seq < 0:
        raise ValueError("PLU sequence must be non-negative")
    if seq > 999_999:
        raise ValueError("PLU sequence exceeds 6-digit EAN-8 range (max 999_999)")
    body = f"{PLU_PREFIX}{seq:0{PLU_SEQUENCE_DIGITS}d}"
    return f"{body}{compute_ean8_check_digit(body)}"


# ── EAN-13 primitives (legacy reads only) ────────────────────────────────────


def compute_ean13_check_digit(code12: str) -> str:
    """Return the EAN-13 check digit for a 12-digit body string. Legacy only."""
    if len(code12) != _LEGACY_PLU_BODY_DIGITS or not code12.isdigit():
        raise ValueError(f"EAN-13 body must be exactly 12 digits, got {code12!r}")
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(code12))
    return str((10 - (total % 10)) % 10)


def is_valid_ean13(code: str | None) -> bool:
    """True for legacy 13-digit ``200…`` PLUs. Do not use for new allocations."""
    if code is None:
        return False
    text = str(code).strip()
    if len(text) != 13 or not text.isdigit():
        return False
    return compute_ean13_check_digit(text[:12]) == text[12]


# ── SKU / PLU sequence helpers ───────────────────────────────────────────────


def parse_sku_sequence(sku_code: str | None) -> int | None:
    if not sku_code:
        return None
    match = _SKU_SEQUENCE_RE.search(str(sku_code).strip())
    if not match:
        return None
    return int(match.group(1))


def parse_nec_plu_sequence(plu_code: str | None, require_valid: bool = True) -> int | None:
    """Parse the seq number from a PLU.

    Recognises EAN-8 codes (``2`` + 6-digit seq + check). Returns ``None``
    for legacy 13-digit codes — legacy callers that need to read those should
    use :func:`parse_legacy_ean13_plu_sequence` instead.
    """
    if not plu_code:
        return None
    code = str(plu_code).strip()
    if len(code) != PLU_TOTAL_DIGITS or not code.isdigit() or not code.startswith(PLU_PREFIX):
        return None
    if require_valid and not is_valid_ean8(code):
        return None
    return int(code[len(PLU_PREFIX):PLU_BODY_DIGITS])


def parse_legacy_ean13_plu_sequence(
    plu_code: str | None, require_valid: bool = True
) -> int | None:
    """Parse a legacy 13-digit ``200…`` PLU's 9-digit seq. Migration use only."""
    if not plu_code:
        return None
    code = str(plu_code).strip()
    if len(code) != 13 or not code.isdigit() or not code.startswith(_LEGACY_PLU_PREFIX):
        return None
    if require_valid and not is_valid_ean13(code):
        return None
    return int(code[len(_LEGACY_PLU_PREFIX):_LEGACY_PLU_BODY_DIGITS])


def aligned_nec_plu_for_sku(sku_code: str | None) -> str | None:
    seq = parse_sku_sequence(sku_code)
    if seq is None:
        return None
    if seq > 999_999:
        return None  # SKU seq exceeds EAN-8 range; legacy code, not realignable
    return generate_nec_plu(seq)


def is_sku_plu_aligned(sku_code: str | None, plu_code: str | None) -> bool:
    if not sku_code or not plu_code:
        return False
    expected = aligned_nec_plu_for_sku(sku_code)
    return expected == str(plu_code).strip() if expected else False


def max_sku_sequence(codes: Iterable[str | None]) -> int:
    maximum = 0
    for code in codes:
        seq = parse_sku_sequence(code)
        if seq is not None:
            maximum = max(maximum, seq)
    return maximum


def max_valid_plu_sequence(codes: Iterable[str | None]) -> int:
    """Max sequence among **EAN-8** codes only. Legacy 13-digit codes are ignored.

    This is intentional: after the switch we want allocations to start from
    seq=1 again (modulo SKU collisions handled by ``allocate_identifier_pair``),
    so the 13 pre-printed Hengwei homeware labels can claim seq 1–13.
    """
    maximum = 0
    for code in codes:
        seq = parse_nec_plu_sequence(code, require_valid=True)
        if seq is not None:
            maximum = max(maximum, seq)
    return maximum


def allocate_identifier_pair(
    sku_factory: Callable[[int], str],
    existing_sku_codes: set[str],
    existing_plus: set[str],
    next_seq: int,
) -> tuple[str, str, int]:
    seq = max(1, int(next_seq))
    while True:
        sku_code = sku_factory(seq)
        plu_code = generate_nec_plu(seq)
        if sku_code not in existing_sku_codes and plu_code not in existing_plus:
            existing_sku_codes.add(sku_code)
            existing_plus.add(plu_code)
            return sku_code, plu_code, seq + 1
        seq += 1


__all__ = [
    "PLU_PREFIX",
    "PLU_BODY_DIGITS",
    "PLU_SEQUENCE_DIGITS",
    "PLU_TOTAL_DIGITS",
    "SKU_SEQUENCE_DIGITS",
    "aligned_nec_plu_for_sku",
    "allocate_identifier_pair",
    "compute_ean8_check_digit",
    "compute_ean13_check_digit",
    "generate_nec_plu",
    "is_sku_plu_aligned",
    "is_valid_ean8",
    "is_valid_ean13",
    "is_valid_plu",
    "max_sku_sequence",
    "max_valid_plu_sequence",
    "parse_legacy_ean13_plu_sequence",
    "parse_nec_plu_sequence",
    "parse_sku_sequence",
]
