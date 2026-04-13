from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------- Account ----------

class AccountCreate(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    account_type: str  # asset, liability, equity, revenue, expense
    parent_id: Optional[UUID] = None
    description: Optional[str] = Field(None, max_length=500)
    is_active: bool = True
    store_id: Optional[UUID] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    parent_id: Optional[UUID] = None


class AccountRead(BaseModel):
    id: UUID
    code: str
    name: str
    account_type: str
    parent_id: Optional[UUID] = None
    description: Optional[str] = None
    is_active: bool
    store_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Journal Line ----------

class JournalLineCreate(BaseModel):
    account_id: UUID
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: Optional[str] = Field(None, max_length=500)


class JournalLineRead(BaseModel):
    id: UUID
    journal_entry_id: UUID
    account_id: UUID
    debit: Decimal
    credit: Decimal
    description: Optional[str] = None
    account_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Journal Entry ----------

class JournalEntryCreate(BaseModel):
    entry_date: date
    description: str = Field(..., max_length=500)
    source_type: str = "manual"
    source_ref: Optional[str] = Field(None, max_length=255)
    lines: list[JournalLineCreate] = Field(..., min_length=2)


class JournalEntryUpdate(BaseModel):
    entry_date: Optional[date] = None
    description: Optional[str] = Field(None, max_length=500)
    source_type: Optional[str] = None
    source_ref: Optional[str] = Field(None, max_length=255)


class JournalEntryRead(BaseModel):
    id: UUID
    entry_number: str
    entry_date: date
    description: str
    store_id: UUID
    source_type: str
    source_ref: Optional[str] = None
    is_posted: bool
    posted_by: Optional[UUID] = None
    created_by: UUID
    lines: list[JournalLineRead] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Reporting ----------

class AccountBalance(BaseModel):
    account_id: UUID
    account_name: str
    account_code: str
    account_type: str
    debit_total: Decimal
    credit_total: Decimal
    balance: Decimal


class LedgerEntry(BaseModel):
    journal_entry_id: UUID
    entry_number: str
    entry_date: date
    journal_description: str
    line_description: Optional[str] = None
    debit: Decimal
    credit: Decimal
    source_type: str
