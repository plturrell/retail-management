from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.supplier import Supplier, SupplierProduct
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.common import DataResponse, PaginatedResponse
from app.schemas.supplier import (
    SupplierCreate,
    SupplierProductCreate,
    SupplierProductRead,
    SupplierProductUpdate,
    SupplierRead,
    SupplierUpdate,
)

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("", response_model=PaginatedResponse[SupplierRead])
async def list_suppliers(
    page: int = 1,
    page_size: int = 50,
    search: str | None = Query(None, max_length=100),
    is_active: bool | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Supplier)
    if search:
        term = f"%{search}%"
        q = q.where(Supplier.name.ilike(term) | Supplier.supplier_code.ilike(term))
    if is_active is not None:
        q = q.where(Supplier.is_active == is_active)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    return PaginatedResponse(
        data=[SupplierRead.model_validate(s) for s in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{supplier_id}", response_model=DataResponse[SupplierRead])
async def get_supplier(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return DataResponse(data=SupplierRead.model_validate(supplier))


@router.post("", response_model=DataResponse[SupplierRead], status_code=201)
async def create_supplier(
    payload: SupplierCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    await db.flush()
    await db.refresh(supplier)
    return DataResponse(data=SupplierRead.model_validate(supplier))


@router.patch("/{supplier_id}", response_model=DataResponse[SupplierRead])
async def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, key, value)
    await db.flush()
    await db.refresh(supplier)
    return DataResponse(data=SupplierRead.model_validate(supplier))


@router.delete("/{supplier_id}", status_code=204)
async def delete_supplier(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    await db.delete(supplier)


# ---------- Supplier Products ----------

@router.get("/{supplier_id}/products", response_model=DataResponse[list[SupplierProductRead]])
async def list_supplier_products(
    supplier_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id)
    )
    return DataResponse(data=[SupplierProductRead.model_validate(p) for p in result.scalars().all()])


@router.post("/{supplier_id}/products", response_model=DataResponse[SupplierProductRead], status_code=201)
async def add_supplier_product(
    supplier_id: UUID,
    payload: SupplierProductCreate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    product = SupplierProduct(**payload.model_dump())
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return DataResponse(data=SupplierProductRead.model_validate(product))


@router.patch("/{supplier_id}/products/{product_id}", response_model=DataResponse[SupplierProductRead])
async def update_supplier_product(
    supplier_id: UUID,
    product_id: UUID,
    payload: SupplierProductUpdate,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SupplierProduct).where(
            SupplierProduct.id == product_id, SupplierProduct.supplier_id == supplier_id
        )
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Supplier product not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    await db.flush()
    await db.refresh(product)
    return DataResponse(data=SupplierProductRead.model_validate(product))


@router.delete("/{supplier_id}/products/{product_id}", status_code=204)
async def delete_supplier_product(
    supplier_id: UUID,
    product_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SupplierProduct).where(
            SupplierProduct.id == product_id, SupplierProduct.supplier_id == supplier_id
        )
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Supplier product not found")
    await db.delete(product)
