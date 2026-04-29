from __future__ import annotations

import re
from typing import Callable, Iterable

PLU_PREFIX = "200"
PLU_BODY_DIGITS = 12
PLU_SEQUENCE_DIGITS = 9
SKU_SEQUENCE_DIGITS = 7

_SKU_SEQUENCE_RE = re.compile(r"(\d{7})$")


def compute_ean13_check_digit(code12: str) -> str:
    if len(code12) != PLU_BODY_DIGITS or not code12.isdigit():
        raise ValueError(f"EAN-13 body must be exactly 12 digits, got {code12!r}")
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(code12))
    return str((10 - (total % 10)) % 10)


def is_valid_ean13(code: str | None) -> bool:
    if code is None:
        return False
    text = str(code).strip()
    if len(text) != 13 or not text.isdigit():
        return False
    return compute_ean13_check_digit(text[:12]) == text[12]


def generate_nec_plu(seq: int) -> str:
    if seq < 0:
        raise ValueError("PLU sequence must be non-negative")
    if seq > 999_999_999:
        raise ValueError("PLU sequence exceeds 9-digit NEC range")
    code12 = f"{PLU_PREFIX}{seq:09d}"
    return f"{code12}{compute_ean13_check_digit(code12)}"


def parse_sku_sequence(sku_code: str | None) -> int | None:
    if not sku_code:
        return None
    match = _SKU_SEQUENCE_RE.search(str(sku_code).strip())
    if not match:
        return None
    return int(match.group(1))


def parse_nec_plu_sequence(plu_code: str | None, require_valid: bool = True) -> int | None:
    if not plu_code:
        return None
    code = str(plu_code).strip()
    if len(code) != 13 or not code.isdigit() or not code.startswith(PLU_PREFIX):
        return None
    if require_valid and not is_valid_ean13(code):
        return None
    return int(code[len(PLU_PREFIX):12])


def aligned_nec_plu_for_sku(sku_code: str | None) -> str | None:
    seq = parse_sku_sequence(sku_code)
    if seq is None:
        return None
    return generate_nec_plu(seq)


def is_sku_plu_aligned(sku_code: str | None, plu_code: str | None) -> bool:
    if not sku_code or not plu_code:
        return False
    expected = aligned_nec_plu_for_sku(sku_code)
    return expected == str(plu_code).strip() if expected else False


def validate_identifier_pair(
    sku_code: str | None,
    plu_code: str | None,
    *,
    require_alignment: bool = True,
) -> None:
    if not sku_code:
        raise ValueError("Missing sku_code")
    if not plu_code:
        raise ValueError(f"Missing nec_plu for SKU {sku_code}")
    if not is_valid_ean13(plu_code):
        raise ValueError(f"Invalid EAN-13 check digit for SKU {sku_code}: {plu_code}")
    if require_alignment and not is_sku_plu_aligned(sku_code, plu_code):
        expected = aligned_nec_plu_for_sku(sku_code)
        raise ValueError(
            f"PLU {plu_code} does not align with SKU {sku_code}; expected {expected}"
        )


def max_sku_sequence(codes: Iterable[str | None]) -> int:
    maximum = 0
    for code in codes:
        seq = parse_sku_sequence(code)
        if seq is not None:
            maximum = max(maximum, seq)
    return maximum


def max_valid_plu_sequence(codes: Iterable[str | None]) -> int:
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
