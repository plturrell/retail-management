from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampMixin, UUIDMixin


class UserBase(BaseModel):
    email: str = Field(..., max_length=255)
    full_name: str = Field(..., max_length=255)
    phone: str | None = Field(None, max_length=50)


class UserCreate(UserBase):
    firebase_uid: str = Field(..., max_length=128)


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)


class UserRead(UserBase, UUIDMixin, TimestampMixin):
    firebase_uid: str
    model_config = ConfigDict(from_attributes=True)


class UserStoreRoleBase(BaseModel):
    user_id: UUID
    store_id: UUID
    role: str


class UserStoreRoleCreate(UserStoreRoleBase):
    pass


class UserStoreRoleUpdate(BaseModel):
    role: str


class UserStoreRoleRead(UserStoreRoleBase, UUIDMixin):
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class UserMeRead(UserBase, UUIDMixin, TimestampMixin):
    firebase_uid: str
    store_roles: list[UserStoreRoleRead] = []
    model_config = ConfigDict(from_attributes=True)


class StoreEmployeeRead(BaseModel):
    id: UUID
    role_id: UUID
    full_name: str
    email: str
    phone: str | None = None
    role: str
    model_config = ConfigDict(from_attributes=True)
