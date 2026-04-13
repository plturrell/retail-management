import enum
import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Numeric,
    String,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class AccountType(str, enum.Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    revenue = "revenue"
    expense = "expense"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SQLEnum(AccountType, name="account_type_enum"), nullable=False
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    parent = relationship("Account", remote_side="Account.id", lazy="raise")
    store = relationship("Store", lazy="raise")
    journal_lines = relationship("JournalLine", back_populates="account", lazy="raise")

    def __repr__(self) -> str:
        return f"<Account {self.code}: {self.name}>"


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[uuid_pk]
    entry_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    entry_date: Mapped["date"] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", lazy="raise")
    poster = relationship("User", foreign_keys=[posted_by], lazy="raise")
    creator = relationship("User", foreign_keys=[created_by], lazy="raise")
    lines = relationship(
        "JournalLine",
        back_populates="journal_entry",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<JournalEntry {self.entry_number}>"


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id: Mapped[uuid_pk]
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    debit: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    credit: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[created_at_col]

    # Relationships
    journal_entry = relationship("JournalEntry", back_populates="lines", lazy="raise")
    account = relationship("Account", back_populates="journal_lines", lazy="raise")

    def __repr__(self) -> str:
        return f"<JournalLine entry={self.journal_entry_id} dr={self.debit} cr={self.credit}>"
