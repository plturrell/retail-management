from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampMixin, UUIDMixin


class BankTransactionRead(UUIDMixin, TimestampMixin):
    store_id: UUID
    source: str
    transaction_date: date
    description: str
    reference: Optional[str] = None
    amount: float
    balance: Optional[float] = None
    category: Optional[str] = None
    account_id: Optional[UUID] = None
    journal_entry_id: Optional[UUID] = None
    is_reconciled: bool = False
    raw_data: Optional[str] = None


class BankTransactionUpdate(BaseModel):
    category: Optional[str] = Field(None, max_length=100)
    account_id: Optional[UUID] = None


class BankTransactionReconcile(BaseModel):
    account_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=500)


class OCBCImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = []


class WebhookResult(BaseModel):
    success: bool = True
    transaction_id: Optional[UUID] = None
    message: str = "OK"
