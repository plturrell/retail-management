"""SQLAlchemy declarative base for all TiDB-backed ORM models."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base class — collects all table metadata for alembic autogenerate."""
