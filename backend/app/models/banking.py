import uuid
from datetime import date
from typing import Optional
from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "reference",
            "transaction_date",
            "amount",
            name="uq_bank_txn_source_ref_date_amount",
        ),
    )

    id: Mapped[uuid_pk]
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    balance: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Reconciliation links to the finance ledger. NULL until the bank txn is
    # categorised / posted to a chart-of-accounts entry. ON DELETE SET NULL so
    # that pruning a journal entry doesn't cascade-delete its bank evidence.
    # NOTE: the alembic graph currently has multiple heads (two `007`s); the
    # production DB FK constraints for these columns must be added once the
    # tree is consolidated. Until then, referential integrity is enforced at
    # the ORM layer only.
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    journal_entry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_reconciled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    raw_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", lazy="raise")

    def __repr__(self) -> str:
        return f"<BankTransaction {self.source} {self.reference} {self.amount}>"
