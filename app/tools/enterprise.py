"""Read-only application tools for employee business questions."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.services.data_center import DataCenterService
from app.services.product_structure import ProductStructureService


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SupplierQuery(_Input):
    search: str | None = Field(default=None, max_length=100)


class SupplierPartsQuery(_Input):
    supplier: str | None = Field(default=None, max_length=100)
    part_number: str | None = Field(default=None, max_length=64)


class PartQuery(_Input):
    part_number: str = Field(min_length=1, max_length=64)


class PartRevisionQuery(PartQuery):
    as_of_date: date | None = None


class OrderQuery(_Input):
    order_number: str | None = Field(default=None, max_length=64)


class PurchaseQuery(OrderQuery):
    open_only: bool = False
    supplier_code: str | None = Field(default=None, max_length=64)


def get_suppliers(request: SupplierQuery, *, service: DataCenterService | None = None):
    return (service or DataCenterService()).suppliers(request.search)


def get_supplier_parts(request: SupplierPartsQuery, *, service: DataCenterService | None = None):
    return (service or DataCenterService()).supplier_parts(request.supplier, request.part_number)


def get_part_revisions(request: PartRevisionQuery, *, service: ProductStructureService | None = None):
    active = service or ProductStructureService()
    return {
        "part_number": request.part_number,
        "revisions": active.list_revision_codes(request.part_number),
        "effective_revisions": active.effective_revision_codes(request.part_number, request.as_of_date),
        "as_of_date": request.as_of_date or active.current_business_date(),
    }


def get_purchase_order_records(request: PurchaseQuery, *, service: DataCenterService | None = None):
    active = service or DataCenterService()
    if request.order_number:
        return active.purchase_order(request.order_number)
    return active.purchase_orders(
        open_only=request.open_only, supplier_code=request.supplier_code,
    )


def get_production_order_records(request: OrderQuery, *, service: DataCenterService | None = None):
    active = service or DataCenterService()
    return active.production_order(request.order_number) if request.order_number else active.production_orders()


def get_production_orders_for_part(request: PartQuery, *, service: DataCenterService | None = None):
    return (service or DataCenterService()).production_orders_for_part(request.part_number)


def get_sales_order_records(request: OrderQuery, *, service: DataCenterService | None = None):
    active = service or DataCenterService()
    return active.sales_order(request.order_number) if request.order_number else active.sales_orders()
