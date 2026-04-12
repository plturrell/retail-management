import uuid
from datetime import time
from sqlalchemy import Boolean, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    business_hours_start: Mapped[time] = mapped_column(Time, nullable=False)
    business_hours_end: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    user_roles = relationship("UserStoreRole", back_populates="store", lazy="selectin")
    categories = relationship("Category", back_populates="store", lazy="selectin")
    skus = relationship("SKU", back_populates="store", lazy="selectin")
    prices = relationship("Price", back_populates="store", lazy="selectin")
    inventories = relationship("Inventory", back_populates="store", lazy="selectin")
    orders = relationship("Order", back_populates="store", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Store {self.name}>"
