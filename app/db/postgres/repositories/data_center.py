"""企业数据中心使用的只读 ERP 查询。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select

from app.db.postgres.models.erp import (
    InventoryBalance,
    ProductionMaterialRequirement,
    ProductionOrder,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    SalesOrderLine,
    Supplier,
    SupplierPart,
)
from app.db.postgres.repositories.base import ReadOnlyRepository


class DataCenterRepository(ReadOnlyRepository):
    """只返回可序列化字段，不向 Service 暴露 ORM 实例。"""

    def summary(self) -> dict[str, int]:
        tables = {
            "suppliers": Supplier,
            "supplier_parts": SupplierPart,
            "inventory": InventoryBalance,
            "purchase_orders": PurchaseOrder,
            "purchase_order_lines": PurchaseOrderLine,
            "production_orders": ProductionOrder,
            "production_material_requirements": ProductionMaterialRequirement,
            "sales_orders": SalesOrder,
            "sales_order_lines": SalesOrderLine,
        }
        return {
            name: int(self._fetch_all(select(func.count()).select_from(model))[0][0])
            for name, model in tables.items()
        }

    def suppliers(self, search: str | None = None) -> list[dict[str, Any]]:
        statement = select(
            Supplier.supplier_code, Supplier.supplier_name, Supplier.status,
            Supplier.quality_rating, Supplier.delivery_rating,
        ).order_by(Supplier.supplier_code)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(or_(
                Supplier.supplier_code.ilike(pattern), Supplier.supplier_name.ilike(pattern)
            ))
        return self._records(statement)

    def supplier_parts(
        self, supplier: str | None = None, part_number: str | None = None
    ) -> list[dict[str, Any]]:
        statement = (
            select(
                Supplier.supplier_code, Supplier.supplier_name,
                SupplierPart.part_number, SupplierPart.revision_code,
                SupplierPart.manufacturer_part_number, SupplierPart.status,
                SupplierPart.qualification_status, SupplierPart.unit_price,
                SupplierPart.currency, SupplierPart.lead_time_days,
                SupplierPart.minimum_order_qty, SupplierPart.last_time_buy_date,
                SupplierPart.eol_date,
            )
            .join(Supplier, Supplier.supplier_id == SupplierPart.supplier_id)
            .order_by(Supplier.supplier_code, SupplierPart.part_number)
        )
        if supplier:
            pattern = f"%{supplier}%"
            statement = statement.where(or_(
                Supplier.supplier_code.ilike(pattern), Supplier.supplier_name.ilike(pattern)
            ))
        if part_number:
            statement = statement.where(SupplierPart.part_number.ilike(f"%{part_number}%"))
        return self._records(statement)

    def inventory(self, part_number: str | None = None) -> list[dict[str, Any]]:
        statement = select(
            InventoryBalance.plant_code, InventoryBalance.warehouse_code,
            InventoryBalance.part_number, InventoryBalance.revision_code,
            InventoryBalance.qty_on_hand, InventoryBalance.qty_reserved,
            InventoryBalance.unit_cost, InventoryBalance.currency,
        ).order_by(
            InventoryBalance.part_number, InventoryBalance.plant_code,
            InventoryBalance.warehouse_code,
        )
        if part_number:
            statement = statement.where(InventoryBalance.part_number.ilike(f"%{part_number}%"))
        return self._records(statement)

    def purchase_orders(self, *, open_only: bool = False) -> list[dict[str, Any]]:
        statement = (
            select(
                PurchaseOrder.po_number.label("order_number"), Supplier.supplier_code,
                Supplier.supplier_name, PurchaseOrder.status,
                PurchaseOrder.order_date, PurchaseOrder.expected_date,
                PurchaseOrder.currency,
            )
            .join(Supplier, Supplier.supplier_id == PurchaseOrder.supplier_id)
            .order_by(PurchaseOrder.po_number)
        )
        if open_only:
            statement = statement.where(PurchaseOrder.status.not_in(("COMPLETED", "CANCELLED")))
        return self._records(statement)

    def purchase_order_lines(self, order_number: str) -> list[dict[str, Any]]:
        return self._records(
            select(
                PurchaseOrderLine.line_number, PurchaseOrderLine.part_number,
                PurchaseOrderLine.revision_code, PurchaseOrderLine.ordered_qty,
                PurchaseOrderLine.received_qty, PurchaseOrderLine.unit_price,
                PurchaseOrderLine.expected_date, PurchaseOrderLine.status,
            )
            .join(PurchaseOrder, PurchaseOrder.po_id == PurchaseOrderLine.po_id)
            .where(PurchaseOrder.po_number == order_number)
            .order_by(PurchaseOrderLine.line_number)
        )

    def production_orders(self) -> list[dict[str, Any]]:
        return self._records(
            select(
                ProductionOrder.order_number, ProductionOrder.product_part_number,
                ProductionOrder.product_revision, ProductionOrder.status,
                ProductionOrder.planned_qty, ProductionOrder.completed_qty,
                ProductionOrder.planned_start, ProductionOrder.planned_end,
            ).order_by(ProductionOrder.order_number)
        )

    def production_requirements(self, order_number: str) -> list[dict[str, Any]]:
        return self._records(
            select(
                ProductionMaterialRequirement.line_number,
                ProductionMaterialRequirement.part_number,
                ProductionMaterialRequirement.revision_code,
                ProductionMaterialRequirement.required_qty,
                ProductionMaterialRequirement.reserved_qty,
                ProductionMaterialRequirement.issued_qty,
            )
            .join(
                ProductionOrder,
                ProductionOrder.production_order_id
                == ProductionMaterialRequirement.production_order_id,
            )
            .where(ProductionOrder.order_number == order_number)
            .order_by(ProductionMaterialRequirement.line_number)
        )

    def production_orders_for_part(self, part_number: str) -> list[dict[str, Any]]:
        return self._records(
            select(
                ProductionOrder.order_number,
                ProductionOrder.product_part_number,
                ProductionOrder.product_revision,
                ProductionOrder.status,
                ProductionOrder.planned_qty,
                ProductionMaterialRequirement.required_qty,
                ProductionMaterialRequirement.reserved_qty,
                ProductionMaterialRequirement.issued_qty,
            )
            .join(
                ProductionMaterialRequirement,
                ProductionOrder.production_order_id
                == ProductionMaterialRequirement.production_order_id,
            )
            .where(ProductionMaterialRequirement.part_number == part_number)
            .order_by(ProductionOrder.order_number)
        )

    def sales_orders(self) -> list[dict[str, Any]]:
        return self._records(
            select(
                SalesOrder.order_number, SalesOrder.customer_code, SalesOrder.status,
                SalesOrder.order_date, SalesOrder.requested_delivery_date,
            ).order_by(SalesOrder.order_number)
        )

    def sales_order_lines(self, order_number: str) -> list[dict[str, Any]]:
        return self._records(
            select(
                SalesOrderLine.line_number, SalesOrderLine.product_part_number,
                SalesOrderLine.product_revision, SalesOrderLine.ordered_qty,
                SalesOrderLine.delivered_qty,
                SalesOrderLine.requested_delivery_date,
            )
            .join(SalesOrder, SalesOrder.sales_order_id == SalesOrderLine.sales_order_id)
            .where(SalesOrder.order_number == order_number)
            .order_by(SalesOrderLine.line_number)
        )

    def _records(self, statement: Any) -> list[dict[str, Any]]:
        return [dict(row._mapping) for row in self._fetch_all(statement)]
