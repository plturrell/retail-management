import enum
import uuid
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models._mixins import uuid_pk, created_at_col, updated_at_col


class ScheduleStatusEnum(str, enum.Enum):
    draft = "draft"
    published = "published"


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("store_id", "week_start", name="uq_schedule_store_week_start"),
    )

    id: Mapped[uuid_pk]
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ScheduleStatusEnum] = mapped_column(
        Enum(ScheduleStatusEnum, name="schedule_status_enum"),
        nullable=False,
        default=ScheduleStatusEnum.draft,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    store = relationship("Store", back_populates="schedules", lazy="raise")
    creator = relationship("User", back_populates="created_schedules", lazy="raise")
    shifts = relationship(
        "Shift", back_populates="schedule", lazy="selectin", cascade="all, delete-orphan"
    )  # kept selectin: schedules always need their shifts

    def __repr__(self) -> str:
        return f"<Schedule {self.week_start} status={self.status}>"


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[uuid_pk]
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Relationships
    schedule = relationship("Schedule", back_populates="shifts", lazy="raise")
    user = relationship("User", lazy="raise")

    def __repr__(self) -> str:
        return f"<Shift {self.shift_date} {self.start_time}-{self.end_time}>"
