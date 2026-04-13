"""Airwallex cross-border payment integration service.

Parses Airwallex webhook notifications and payout data
into BankTransactionData for import.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from app.services.ocbc_parser import BankTransactionData


def _parse_iso_date(dt_str: str) -> date:
    """Parse an ISO 8601 datetime string and return the date portion."""
    return date.fromisoformat(dt_str[:10])


def parse_airwallex_webhook(payload: dict) -> BankTransactionData:
    """Parse an Airwallex webhook notification into a BankTransactionData.

    Expected payload:
    {
        "id": "pa_abc123",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "int_abc123",
                "amount": 150.00,
                "currency": "SGD",
                "status": "SUCCEEDED",
                "merchant_order_id": "ORD-002",
                "created_at": "2026-05-01T15:00:00Z"
            }
        }
    }
    """
    event_id = payload.get("id", "")
    event_type = payload.get("type", "")
    data_obj = payload.get("data", {}).get("object", {})

    amount = float(data_obj.get("amount", 0))
    currency = data_obj.get("currency", "SGD")
    merchant_order_id = data_obj.get("merchant_order_id", "")
    created_at = data_obj.get("created_at", "")
    intent_id = data_obj.get("id", "")

    txn_date = _parse_iso_date(created_at) if created_at else date.today()

    description = f"Airwallex {event_type}"
    if merchant_order_id:
        description += f" - {merchant_order_id}"

    # Use the intent ID as reference, fall back to event ID
    reference = intent_id or event_id

    raw_data = json.dumps(payload)

    return BankTransactionData(
        source="airwallex",
        transaction_date=txn_date,
        description=description,
        amount=amount,
        reference=reference,
        balance=None,
        category="cross_border_payment",
        raw_data=raw_data,
    )


def parse_airwallex_payout(data: dict) -> BankTransactionData:
    """Parse an Airwallex payout notification into a BankTransactionData.

    Expected structure:
    {
        "payout_id": "po_abc123",
        "amount": 1000.00,
        "currency": "SGD",
        "status": "COMPLETED",
        "created_at": "2026-05-01T12:00:00Z",
        "description": "Weekly payout"
    }
    """
    payout_id = data.get("payout_id", "")
    amount = float(data.get("amount", 0))
    created_at = data.get("created_at", "")
    payout_desc = data.get("description", "Airwallex payout")

    txn_date = _parse_iso_date(created_at) if created_at else date.today()

    raw_data = json.dumps(data)

    return BankTransactionData(
        source="airwallex",
        transaction_date=txn_date,
        description=payout_desc,
        amount=amount,
        reference=payout_id,
        balance=None,
        category="payout",
        raw_data=raw_data,
    )
