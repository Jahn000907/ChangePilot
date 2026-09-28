"""企业数据中心只读 HTTP 接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.domain.dto.data_center import (
    DataSummary,
    InventoryRow,
    ProductionOrderDetail,
    ProductionOrderRow,
    PurchaseOrderDetail,
    PurchaseOrderRow,
    SalesOrderDetail,
    SalesOrderRow,
    SupplierPartRow,
    SupplierRow,
)
from app.services.data_center import DataCenterService

router = APIRouter(prefix="/api/v1/data", tags=["data-center"])


def get_data_center_service() -> DataCenterService:
    return DataCenterService()


Service = Annotated[DataCenterService, Depends(get_data_center_service)]
Search = Annotated[str | None, Query(max_length=100)]


@router.get("/summary", response_model=DataSummary)
def summary(service: Service) -> DataSummary:
    return service.summary()


@router.get("/suppliers", response_model=list[SupplierRow])
def suppliers(service: Service, search: Search = None) -> list[SupplierRow]:
    return service.suppliers(search)


@router.get("/supplier-parts", response_model=list[SupplierPartRow])
def supplier_parts(
    service: Service, supplier: Search = None, part_number: Search = None
) -> list[SupplierPartRow]:
    return service.supplier_parts(supplier, part_number)


@router.get("/inventory", response_model=list[InventoryRow])
def inventory(service: Service, part_number: Search = None) -> list[InventoryRow]:
    return service.inventory(part_number)


@router.get("/purchase-orders", response_model=list[PurchaseOrderRow])
def purchase_orders(service: Service) -> list[PurchaseOrderRow]:
    return service.purchase_orders()


@router.get("/purchase-orders/{order_number}", response_model=PurchaseOrderDetail)
def purchase_order(order_number: str, service: Service) -> PurchaseOrderDetail:
    try:
        return service.purchase_order(order_number)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/production-orders", response_model=list[ProductionOrderRow])
def production_orders(service: Service) -> list[ProductionOrderRow]:
    return service.production_orders()


@router.get("/production-orders/{order_number}", response_model=ProductionOrderDetail)
def production_order(order_number: str, service: Service) -> ProductionOrderDetail:
    try:
        return service.production_order(order_number)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sales-orders", response_model=list[SalesOrderRow])
def sales_orders(service: Service) -> list[SalesOrderRow]:
    return service.sales_orders()


@router.get("/sales-orders/{order_number}", response_model=SalesOrderDetail)
def sales_order(order_number: str, service: Service) -> SalesOrderDetail:
    try:
        return service.sales_order(order_number)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
