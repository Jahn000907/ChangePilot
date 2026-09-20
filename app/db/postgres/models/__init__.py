"""PostgreSQL ORM models.

Importing this package registers every model on ``Base.metadata``, which is
what Alembic autogenerate compares against. Every new model module must be
imported and re-exported here.
"""

from __future__ import annotations

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

__all__ = [
    "InventoryBalance",
    "ProductionMaterialRequirement",
    "ProductionOrder",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "SalesOrder",
    "SalesOrderLine",
    "Supplier",
    "SupplierPart",
]
