import enum
import uuid
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import Boolean, Enum as SQLEnum, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class StoreTypeEnum(str, enum.Enum):
    flagship = "flagship"
    outlet = "outlet"
    pop_up = "pop_up"
    warehouse = "warehouse"
    online = "online"


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[uuid_pk]
    store_code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    store_type: Mapped[StoreTypeEnum] = mapped_column(
        SQLEnum(StoreTypeEnum, name="store_type_enum"),
        default=StoreTypeEnum.outlet,
        nullable=False,
    )
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str] = mapped_column(String(100), default="Singapore", nullable=False)
    country: Mapped[str] = mapped_column(String(100), default="Singapore", nullable=False)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    business_hours_start: Mapped[time] = mapped_column(Time, nullable=False)
    business_hours_end: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    user_roles = relationship("UserStoreRole", back_populates="store", lazy="raise")
    categories = relationship("Category", back_populates="store", lazy="raise")
    skus = relationship("SKU", back_populates="store", lazy="raise")
    prices = relationship("Price", back_populates="store", lazy="raise")
    inventories = relationship("Inventory", back_populates="store", lazy="raise")
    orders = relationship("Order", back_populates="store", lazy="raise")
    schedules = relationship("Schedule", back_populates="store", lazy="raise")
    time_entries = relationship("TimeEntry", back_populates="store", lazy="raise")

    def __repr__(self) -> str:
        return f"<Store {self.store_code}: {self.name}>"
