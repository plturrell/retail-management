from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

T = TypeVar("T")


class BaseResponse(BaseModel):
    success: bool = True
    message: str = "OK"


class DataResponse(BaseResponse, Generic[T]):
    data: T


class PaginatedResponse(BaseResponse, Generic[T]):
    data: list[T]
    total: int
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    detail: Any = None


class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class UUIDMixin(BaseModel):
    id: UUID

    model_config = {"from_attributes": True}
