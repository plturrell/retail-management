"""OCBC CSV statement parser.

OCBC CSV format:
Transaction date,Value date,Description,Withdrawals,Deposits,Balance
DD/MM/YYYY,DD/MM/YYYY,"description text",100.00,,5000.00
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class BankTransactionData:
    """Intermediate data transfer object for parsed bank transactions."""
    source: str
    transaction_date: date
    description: str
    amount: float  # positive = credit, negative = debit
    reference: Optional[str] = None
    balance: Optional[float] = None
    category: Optional[str] = None
    raw_data: Optional[str] = None


# Category patterns: (regex, category_name)
_CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"NETS", re.IGNORECASE), "payment_terminal"),
    (re.compile(r"VISA", re.IGNORECASE), "payment_terminal"),
    (re.compile(r"MASTERCARD", re.IGNORECASE), "payment_terminal"),
    (re.compile(r"SALARY|GIRO", re.IGNORECASE), "salary"),
    (re.compile(r"RENT|LEASE", re.IGNORECASE), "rent"),
    (re.compile(r"INTEREST", re.IGNORECASE), "interest"),
]


def _auto_categorise(description: str) -> str:
    """Categorise a transaction based on its description."""
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(description):
            return category
    return "uncategorised"


def _parse_date(date_str: str) -> date:
    """Parse DD/MM/YYYY date format."""
    parts = date_str.strip().split("/")
    if len(parts) != 3:
        raise ValueError(f"Invalid date format: {date_str}")
    day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
    return date(year, month, day)


def _parse_amount(value: str) -> Optional[float]:
    """Parse a numeric amount string, returning None for empty strings."""
    value = value.strip()
    if not value:
        return None
    return float(value.replace(",", ""))


def parse_ocbc_csv(file_content: str) -> list[BankTransactionData]:
    """Parse OCBC CSV statement content into a list of BankTransactionData.

    Withdrawals become negative amounts, deposits become positive.
    """
    reader = csv.reader(io.StringIO(file_content))
    rows = list(reader)

    if not rows:
        return []

    # Find header row
    header_idx = None
    for i, row in enumerate(rows):
        cleaned = [c.strip().lower() for c in row]
        if "transaction date" in cleaned and "description" in cleaned:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find OCBC CSV header row")

    header = [c.strip().lower() for c in rows[header_idx]]

    # Map column indices
    col_map = {}
    for i, col in enumerate(header):
        col_map[col] = i

    required = ["transaction date", "description"]
    for req in required:
        if req not in col_map:
            raise ValueError(f"Missing required column: {req}")

    results: list[BankTransactionData] = []

    for row in rows[header_idx + 1 :]:
        if not row or all(c.strip() == "" for c in row):
            continue

        txn_date_str = row[col_map["transaction date"]].strip()
        if not txn_date_str:
            continue

        txn_date = _parse_date(txn_date_str)
        description = row[col_map["description"]].strip()

        withdrawal = _parse_amount(row[col_map.get("withdrawals", -1)]) if "withdrawals" in col_map else None
        deposit = _parse_amount(row[col_map.get("deposits", -1)]) if "deposits" in col_map else None
        balance = _parse_amount(row[col_map.get("balance", -1)]) if "balance" in col_map else None

        if withdrawal is not None:
            amount = -withdrawal
        elif deposit is not None:
            amount = deposit
        else:
            continue  # skip rows with no amount

        category = _auto_categorise(description)

        # Build a raw CSV representation of the row
        raw_data = ",".join(row)

        # Use description + date as a reference fallback since OCBC CSV
        # does not always contain a dedicated reference column.
        reference = f"OCBC-{txn_date.isoformat()}-{description[:50]}"

        results.append(
            BankTransactionData(
                source="ocbc",
                transaction_date=txn_date,
                description=description,
                amount=amount,
                reference=reference,
                balance=balance,
                category=category,
                raw_data=raw_data,
            )
        )

    return results
