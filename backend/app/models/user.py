import enum
import uuid
from typing import Optional
from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class RoleEnum(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    staff = "staff"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid_pk]
    firebase_uid: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store_roles = relationship("UserStoreRole", back_populates="user", lazy="selectin")
    orders = relationship("Order", back_populates="staff", foreign_keys="[Order.staff_id]", lazy="raise")
    employee_profile = relationship("EmployeeProfile", back_populates="user", uselist=False, lazy="raise")
    created_schedules = relationship("Schedule", back_populates="creator", lazy="raise")
    time_entries = relationship("TimeEntry", back_populates="user", foreign_keys="[TimeEntry.user_id]", lazy="raise")

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class UserStoreRole(Base):
    __tablename__ = "user_store_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "store_id", name="uq_user_store"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum, name="role_enum"), nullable=False
    )
    created_at: Mapped[created_at_col]

    # Relationships
    user = relationship("User", back_populates="store_roles", lazy="raise")
    store = relationship("Store", back_populates="user_roles", lazy="raise")

    def __repr__(self) -> str:
        return f"<UserStoreRole user={self.user_id} store={self.store_id} role={self.role}>"
