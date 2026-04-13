import enum
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class GenderEnum(str, enum.Enum):
    male = "male"
    female = "female"
    other = "other"
    prefer_not_to_say = "prefer_not_to_say"


class LoyaltyTierEnum(str, enum.Enum):
    bronze = "bronze"
    silver = "silver"
    gold = "gold"
    platinum = "platinum"


class LoyaltyTransactionTypeEnum(str, enum.Enum):
    earn = "earn"
    redeem = "redeem"
    adjust = "adjust"
    expire = "expire"


class AddressTypeEnum(str, enum.Enum):
    home = "home"
    work = "work"
    other = "other"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid_pk]
    customer_code: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[GenderEnum]] = mapped_column(
        SQLEnum(GenderEnum, name="customer_gender_enum"), nullable=True
    )
    # Store where customer was registered
    registered_store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    addresses = relationship(
        "CustomerAddress", back_populates="customer", cascade="all, delete-orphan", lazy="raise"
    )
    loyalty_account = relationship(
        "LoyaltyAccount", back_populates="customer", uselist=False, lazy="raise"
    )
    orders = relationship("Order", back_populates="customer", lazy="raise")

    def __repr__(self) -> str:
        return f"<Customer {self.customer_code}: {self.first_name} {self.last_name}>"


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"

    id: Mapped[uuid_pk]
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    address_type: Mapped[AddressTypeEnum] = mapped_column(
        SQLEnum(AddressTypeEnum, name="address_type_enum"),
        default=AddressTypeEnum.home,
        nullable=False,
    )
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="Singapore", nullable=False)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    customer = relationship("Customer", back_populates="addresses", lazy="raise")

    def __repr__(self) -> str:
        return f"<CustomerAddress customer={self.customer_id} type={self.address_type}>"


class LoyaltyAccount(Base):
    __tablename__ = "loyalty_accounts"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_loyalty_customer"),
    )

    id: Mapped[uuid_pk]
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[LoyaltyTierEnum] = mapped_column(
        SQLEnum(LoyaltyTierEnum, name="loyalty_tier_enum"),
        default=LoyaltyTierEnum.bronze,
        nullable=False,
    )
    points_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lifetime_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joined_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    customer = relationship("Customer", back_populates="loyalty_account", lazy="raise")
    transactions = relationship(
        "LoyaltyTransaction", back_populates="loyalty_account", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<LoyaltyAccount customer={self.customer_id} tier={self.tier} pts={self.points_balance}>"


class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"

    id: Mapped[uuid_pk]
    loyalty_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loyalty_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_type: Mapped[LoyaltyTransactionTypeEnum] = mapped_column(
        SQLEnum(LoyaltyTransactionTypeEnum, name="loyalty_txn_type_enum"), nullable=False
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional reference back to the source (order, manual adjustment, etc.)
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[created_at_col]

    # Relationships
    loyalty_account = relationship(
        "LoyaltyAccount", back_populates="transactions", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<LoyaltyTransaction account={self.loyalty_account_id} type={self.transaction_type} pts={self.points}>"
