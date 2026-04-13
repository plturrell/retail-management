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
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class CampaignTypeEnum(str, enum.Enum):
    discount = "discount"
    points_multiplier = "points_multiplier"
    free_gift = "free_gift"
    bundle = "bundle"


class CampaignStatusEnum(str, enum.Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    ended = "ended"


class DiscMethodEnum(str, enum.Enum):
    fixed = "fixed"
    percentage = "percentage"


class VoucherTypeEnum(str, enum.Enum):
    gift_card = "gift_card"
    discount_voucher = "discount_voucher"
    loyalty_voucher = "loyalty_voucher"


class VoucherStatusEnum(str, enum.Enum):
    active = "active"
    redeemed = "redeemed"
    expired = "expired"
    voided = "voided"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid_pk]
    campaign_code: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    campaign_type: Mapped[CampaignTypeEnum] = mapped_column(
        SQLEnum(CampaignTypeEnum, name="campaign_type_enum"), nullable=False
    )
    status: Mapped[CampaignStatusEnum] = mapped_column(
        SQLEnum(CampaignStatusEnum, name="campaign_status_enum"),
        default=CampaignStatusEnum.draft,
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Null store_id means applies to all stores
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True
    )
    budget: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    disc_method: Mapped[Optional[DiscMethodEnum]] = mapped_column(
        SQLEnum(DiscMethodEnum, name="campaign_disc_method_enum"), nullable=True
    )
    disc_value: Mapped[Optional[float]] = mapped_column(Numeric(11, 2), nullable=True)
    points_multiplier: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    min_purchase_amount: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uses_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", lazy="raise")
    skus = relationship("CampaignSKU", back_populates="campaign", lazy="raise")
    categories = relationship("CampaignCategory", back_populates="campaign", lazy="raise")

    def __repr__(self) -> str:
        return f"<Campaign {self.campaign_code}: {self.name} status={self.status}>"


class CampaignSKU(Base):
    """Restricts a campaign to specific SKUs. If no rows exist, campaign applies to all SKUs."""

    __tablename__ = "campaign_skus"
    __table_args__ = (
        UniqueConstraint("campaign_id", "sku_id", name="uq_campaign_sku"),
    )

    id: Mapped[uuid_pk]
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[created_at_col]

    # Relationships
    campaign = relationship("Campaign", back_populates="skus", lazy="raise")
    sku = relationship("SKU", lazy="raise")


class CampaignCategory(Base):
    """Restricts a campaign to specific categories."""

    __tablename__ = "campaign_categories"
    __table_args__ = (
        UniqueConstraint("campaign_id", "category_id", name="uq_campaign_category"),
    )

    id: Mapped[uuid_pk]
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[created_at_col]

    # Relationships
    campaign = relationship("Campaign", back_populates="categories", lazy="raise")
    category = relationship("Category", lazy="raise")


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[uuid_pk]
    voucher_code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    voucher_type: Mapped[VoucherTypeEnum] = mapped_column(
        SQLEnum(VoucherTypeEnum, name="voucher_type_enum"), nullable=False
    )
    face_value: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    # For gift cards, balance decreases as it's used
    balance: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[VoucherStatusEnum] = mapped_column(
        SQLEnum(VoucherStatusEnum, name="voucher_status_enum"),
        default=VoucherStatusEnum.active,
        nullable=False,
    )
    issued_to_customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    issued_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    redeemed_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    issued_to = relationship("Customer", lazy="raise")
    issuer = relationship("User", lazy="raise")

    def __repr__(self) -> str:
        return f"<Voucher {self.voucher_code} type={self.voucher_type} balance={self.balance}>"


class CustomerSegment(Base):
    """Dynamic or static grouping of customers for targeted marketing."""

    __tablename__ = "customer_segments"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # JSON criteria for dynamic segments (e.g., {"min_lifetime_spend": 1000, "loyalty_tier": "gold"})
    criteria: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    is_dynamic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    members = relationship(
        "CustomerSegmentMember",
        back_populates="segment",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<CustomerSegment {self.name}>"


class CustomerSegmentMember(Base):
    __tablename__ = "customer_segment_members"
    __table_args__ = (
        UniqueConstraint("segment_id", "customer_id", name="uq_segment_customer"),
    )

    id: Mapped[uuid_pk]
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[created_at_col]

    # Relationships
    segment = relationship("CustomerSegment", back_populates="members", lazy="raise")
    customer = relationship("Customer", lazy="raise")

    def __repr__(self) -> str:
        return f"<CustomerSegmentMember segment={self.segment_id} customer={self.customer_id}>"
