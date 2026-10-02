"""企业数据中心查询应用服务。"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel

from app.db.postgres.repositories.data_center import DataCenterRepository
from app.domain.dto.data_center import (
    DataSummary,
    InventoryRow,
    ProductionOrderDetail,
    ProductionOrderRow,
    ProductionRequirementRow,
    PurchaseOrderDetail,
    PurchaseOrderLineRow,
    PurchaseOrderRow,
    SalesOrderDetail,
    SalesOrderLineRow,
    SalesOrderRow,
    SupplierPartRow,
    SupplierRow,
)


class _NumberedOrder(Protocol):
    order_number: str


class DataCenterService:
    """把只读数据库记录转换为公开 DTO，并组织订单及其明细。"""

    def __init__(self, repository: DataCenterRepository | None = None) -> None:
        self._repository = repository or DataCenterRepository()

    def summary(self) -> DataSummary:
        return DataSummary.model_validate(self._repository.summary())

    def suppliers(self, search: str | None = None) -> list[SupplierRow]:
        return _rows(SupplierRow, self._repository.suppliers(_query(search)))

    def supplier_parts(
        self, supplier: str | None = None, part_number: str | None = None
    ) -> list[SupplierPartRow]:
        supplier = _query(supplier)
        selected = re.fullmatch(r".+\(\s*(SUP-[A-Z0-9-]+)\s*\)", supplier, re.IGNORECASE) if supplier else None
        if selected:
            supplier = selected.group(1)
        return _rows(
            SupplierPartRow,
            self._repository.supplier_parts(supplier, _query(part_number)),
        )

    def inventory(self, part_number: str | None = None) -> list[InventoryRow]:
        return _rows(InventoryRow, self._repository.inventory(_query(part_number)))

    def purchase_orders(
        self, *, open_only: bool = False, supplier_code: str | None = None
    ) -> list[PurchaseOrderRow]:
        rows = _rows(PurchaseOrderRow, self._repository.purchase_orders(open_only=open_only))
        return [row for row in rows if row.supplier_code == supplier_code] if supplier_code else rows

    def purchase_order(self, order_number: str) -> PurchaseOrderDetail:
        header = _find(self.purchase_orders(), order_number)
        lines = _rows(PurchaseOrderLineRow, self._repository.purchase_order_lines(order_number))
        return PurchaseOrderDetail(**header.model_dump(), lines=lines)

    def production_orders(self) -> list[ProductionOrderRow]:
        return _rows(ProductionOrderRow, self._repository.production_orders())

    def production_orders_for_part(self, part_number: str) -> list[dict[str, object]]:
        return self._repository.production_orders_for_part(part_number.strip())

    def production_order(self, order_number: str) -> ProductionOrderDetail:
        header = _find(self.production_orders(), order_number)
        requirements = _rows(
            ProductionRequirementRow, self._repository.production_requirements(order_number)
        )
        return ProductionOrderDetail(**header.model_dump(), requirements=requirements)

    def sales_orders(self) -> list[SalesOrderRow]:
        return _rows(SalesOrderRow, self._repository.sales_orders())

    def sales_order(self, order_number: str) -> SalesOrderDetail:
        header = _find(self.sales_orders(), order_number)
        lines = _rows(SalesOrderLineRow, self._repository.sales_order_lines(order_number))
        return SalesOrderDetail(**header.model_dump(), lines=lines)


def _query(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _rows[T: BaseModel](model: type[T], records: list[dict[str, object]]) -> list[T]:
    return [model.model_validate(record) for record in records]


def _find[T: _NumberedOrder](orders: list[T], order_number: str) -> T:
    for order in orders:
        if order.order_number == order_number:
            return order
    raise LookupError(f"订单不存在：{order_number}")
