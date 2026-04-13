"""HiPay payment terminal integration service.

Parses HiPay webhook notifications and settlement reports
into BankTransactionData for import.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.services.ocbc_parser import BankTransactionData


def _parse_iso_date(dt_str: str) -> date:
    """Parse an ISO 8601 datetime string and return the date portion."""
    # Handle "2026-05-01T14:30:00Z" and similar formats
    return date.fromisoformat(dt_str[:10])


def parse_hipay_webhook(payload: dict) -> BankTransactionData:
    """Parse a HiPay webhook notification into a BankTransactionData.

    Expected payload:
    {
        "transaction_id": "HP-123456",
        "status": "completed",
        "amount": 299.00,
        "currency": "SGD",
        "payment_method": "card",
        "created_at": "2026-05-01T14:30:00Z",
        "merchant_reference": "ORD-001",
        "customer_email": "customer@example.com"
    }
    """
    txn_id = payload.get("transaction_id", "")
    amount = float(payload.get("amount", 0))
    created_at = payload.get("created_at", "")
    merchant_ref = payload.get("merchant_reference", "")
    payment_method = payload.get("payment_method", "unknown")
    status = payload.get("status", "")

    txn_date = _parse_iso_date(created_at) if created_at else date.today()

    description = f"HiPay {payment_method} payment"
    if merchant_ref:
        description += f" - {merchant_ref}"

    import json
    raw_data = json.dumps(payload)

    return BankTransactionData(
        source="hipay",
        transaction_date=txn_date,
        description=description,
        amount=amount,
        reference=txn_id,
        balance=None,
        category="payment_terminal",
        raw_data=raw_data,
    )


def parse_hipay_settlement(data: dict) -> list[BankTransactionData]:
    """Parse a HiPay settlement report into a list of BankTransactionData.

    Expected structure:
    {
        "settlement_id": "SET-001",
        "settlement_date": "2026-05-01",
        "transactions": [
            { ... same as webhook payload ... }
        ]
    }
    """
    transactions = data.get("transactions", [])
    results: list[BankTransactionData] = []
    for txn in transactions:
        results.append(parse_hipay_webhook(txn))
    return results
