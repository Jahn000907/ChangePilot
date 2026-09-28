"""企业数据中心的稳定只读响应结构。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DataRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataSummary(DataRecord):
    suppliers: int
    supplier_parts: int
    inventory: int
    purchase_orders: int
    purchase_order_lines: int
    production_orders: int
    production_material_requirements: int
    sales_orders: int
    sales_order_lines: int


class SupplierRow(DataRecord):
    supplier_code: str
    supplier_name: str
    status: str
    quality_rating: Decimal
    delivery_rating: Decimal


class SupplierPartRow(DataRecord):
    supplier_code: str
    supplier_name: str
    part_number: str
    revision_code: str | None
    manufacturer_part_number: str
    status: str
    qualification_status: str
    unit_price: Decimal
    currency: str
    lead_time_days: int
    minimum_order_qty: Decimal
    last_time_buy_date: date | None
    eol_date: date | None


class InventoryRow(DataRecord):
    plant_code: str
    warehouse_code: str
    part_number: str
    revision_code: str
    qty_on_hand: Decimal
    qty_reserved: Decimal
    unit_cost: Decimal
    currency: str


class PurchaseOrderRow(DataRecord):
    order_number: str
    supplier_code: str
    supplier_name: str
    status: str
    order_date: date
    expected_date: date | None
    currency: str


class PurchaseOrderLineRow(DataRecord):
    line_number: int
    part_number: str
    revision_code: str
    ordered_qty: Decimal
    received_qty: Decimal
    unit_price: Decimal
    expected_date: date | None
    status: str


class PurchaseOrderDetail(PurchaseOrderRow):
    lines: list[PurchaseOrderLineRow]


class ProductionOrderRow(DataRecord):
    order_number: str
    product_part_number: str
    product_revision: str
    status: str
    planned_qty: Decimal
    completed_qty: Decimal
    planned_start: datetime
    planned_end: datetime


class ProductionRequirementRow(DataRecord):
    line_number: int
    part_number: str
    revision_code: str
    required_qty: Decimal
    reserved_qty: Decimal
    issued_qty: Decimal


class ProductionOrderDetail(ProductionOrderRow):
    requirements: list[ProductionRequirementRow]


class SalesOrderRow(DataRecord):
    order_number: str
    customer_code: str
    status: str
    order_date: date
    requested_delivery_date: date | None


class SalesOrderLineRow(DataRecord):
    line_number: int
    product_part_number: str
    product_revision: str
    ordered_qty: Decimal
    delivered_qty: Decimal
    requested_delivery_date: date | None


class SalesOrderDetail(SalesOrderRow):
    lines: list[SalesOrderLineRow]
