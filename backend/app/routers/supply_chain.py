from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import RoleEnum, get_current_user, require_store_role
from app.schemas.common import DataResponse
from app.schemas.inventory import InventoryType
from app.schemas.supply_chain import (
    BOMRecipeCreate,
    BOMRecipeRead,
    ProductionEventRead,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderReceiveRequest,
    PurchaseReceiptRead,
    PurchaseOrderStatus,
    StageInventoryRead,
    StockTransferCreate,
    StockTransferRead,
    StockTransferReceiveRequest,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
    SupplyChainSummaryRead,
    TransferStatus,
    WorkOrderCompleteRequest,
    WorkOrderRead,
    WorkOrderCreate,
    WorkOrderStatus,
)
from app.services.supply_chain import (
    complete_work_order,
    create_bom_recipe,
    create_purchase_order,
    create_stock_transfer,
    create_supplier,
    create_work_order,
    list_bom_recipes,
    list_production_events,
    list_purchase_orders,
    list_stage_inventory,
    list_stock_transfers,
    list_suppliers,
    list_work_orders,
    receive_purchase_order,
    receive_stock_transfer,
    start_work_order,
    supply_chain_summary,
    update_supplier,
)

router = APIRouter(prefix="/api/stores/{store_id}/supply-chain", tags=["supply-chain"])


@router.get("/summary", response_model=DataResponse[SupplyChainSummaryRead])
async def get_supply_chain_summary(
    store_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=supply_chain_summary(store_id))


@router.get("/stages", response_model=DataResponse[list[StageInventoryRead]])
async def get_stage_inventory(
    store_id: UUID,
    inventory_type: InventoryType | None = None,
    sku_id: UUID | None = None,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=list_stage_inventory(store_id, inventory_type=inventory_type, sku_id=sku_id))


@router.get("/suppliers", response_model=DataResponse[list[SupplierRead]])
async def get_suppliers(
    store_id: UUID,
    active_only: bool = False,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=list_suppliers(store_id, active_only=active_only))


@router.post("/suppliers", response_model=DataResponse[SupplierRead], status_code=201)
async def post_supplier(
    store_id: UUID,
    payload: SupplierCreate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    return DataResponse(data=create_supplier(store_id, payload, user_id))


@router.patch("/suppliers/{supplier_id}", response_model=DataResponse[SupplierRead])
async def patch_supplier(
    store_id: UUID,
    supplier_id: UUID,
    payload: SupplierUpdate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        supplier = update_supplier(store_id, supplier_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return DataResponse(data=supplier)


@router.get("/purchase-orders", response_model=DataResponse[list[PurchaseOrderRead]])
async def get_purchase_orders(
    store_id: UUID,
    status: PurchaseOrderStatus | None = None,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=list_purchase_orders(store_id, status=status))


@router.post("/purchase-orders", response_model=DataResponse[PurchaseOrderRead], status_code=201)
async def post_purchase_order(
    store_id: UUID,
    payload: PurchaseOrderCreate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        order = create_purchase_order(store_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data=order)


@router.post("/purchase-orders/{purchase_order_id}/receive", response_model=DataResponse[dict])
async def post_purchase_receipt(
    store_id: UUID,
    purchase_order_id: UUID,
    payload: PurchaseOrderReceiveRequest,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        order, receipt = receive_purchase_order(store_id, purchase_order_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data={"purchase_order": order, "receipt": receipt})


@router.get("/bom-recipes", response_model=DataResponse[list[BOMRecipeRead]])
async def get_bom_recipes(
    store_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=list_bom_recipes(store_id))


@router.post("/bom-recipes", response_model=DataResponse[BOMRecipeRead], status_code=201)
async def post_bom_recipe(
    store_id: UUID,
    payload: BOMRecipeCreate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        recipe = create_bom_recipe(store_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data=recipe)


@router.get("/work-orders", response_model=DataResponse[list[WorkOrderRead]])
async def get_work_orders(
    store_id: UUID,
    status: WorkOrderStatus | None = None,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=list_work_orders(store_id, status=status))


@router.post("/work-orders", response_model=DataResponse[WorkOrderRead], status_code=201)
async def post_work_order(
    store_id: UUID,
    payload: WorkOrderCreate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        work_order = create_work_order(store_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data=work_order)


@router.post("/work-orders/{work_order_id}/start", response_model=DataResponse[WorkOrderRead])
async def post_start_work_order(
    store_id: UUID,
    work_order_id: UUID,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        work_order = start_work_order(store_id, work_order_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data=work_order)


@router.post("/work-orders/{work_order_id}/complete", response_model=DataResponse[dict])
async def post_complete_work_order(
    store_id: UUID,
    work_order_id: UUID,
    payload: WorkOrderCompleteRequest,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        work_order, event = complete_work_order(store_id, work_order_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data={"work_order": work_order, "event": event})


@router.get("/production-events", response_model=DataResponse[list[ProductionEventRead]])
async def get_production_events(
    store_id: UUID,
    work_order_id: UUID | None = None,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=list_production_events(store_id, work_order_id=work_order_id))


@router.get("/transfers", response_model=DataResponse[list[StockTransferRead]])
async def get_transfers(
    store_id: UUID,
    status: TransferStatus | None = None,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
):
    return DataResponse(data=list_stock_transfers(store_id, status=status))


@router.post("/transfers", response_model=DataResponse[StockTransferRead], status_code=201)
async def post_transfer(
    store_id: UUID,
    payload: StockTransferCreate,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        transfer = create_stock_transfer(store_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data=transfer)


@router.post("/transfers/{transfer_id}/receive", response_model=DataResponse[StockTransferRead])
async def post_receive_transfer(
    store_id: UUID,
    transfer_id: UUID,
    payload: StockTransferReceiveRequest,
    _: dict = Depends(require_store_role(RoleEnum.owner)),
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id")
    if not isinstance(user_id, UUID):
        raise HTTPException(status_code=400, detail="Current user is missing a UUID id")
    try:
        transfer = receive_stock_transfer(store_id, transfer_id, payload, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DataResponse(data=transfer)
