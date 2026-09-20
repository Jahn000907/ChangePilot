"""PostgreSQL ORM models.

Importing this package registers every model on ``Base.metadata``, which is
what Alembic autogenerate compares against. Every new model module must be
imported and re-exported here.
"""

from __future__ import annotations

from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.audit import AuditEvent
from app.db.postgres.models.ecm import (
    ApprovalRecord,
    BOMRedline,
    BOMRedlineLine,
    ChangeCase,
    ChangeImpact,
    ChangeReview,
    ChangeStrategy,
    ChangeStrategyAction,
    EngineeringChangeOrder,
    EngineeringChangeRequest,
    ExecutionJob,
)
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
    "AgentRun",
    "AgentStep",
    "ApprovalRecord",
    "AuditEvent",
    "BOMRedline",
    "BOMRedlineLine",
    "ChangeCase",
    "ChangeImpact",
    "ChangeReview",
    "ChangeStrategy",
    "ChangeStrategyAction",
    "EngineeringChangeOrder",
    "EngineeringChangeRequest",
    "ExecutionJob",
    "InventoryBalance",
    "ProductionMaterialRequirement",
    "ProductionOrder",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "SalesOrder",
    "SalesOrderLine",
    "Supplier",
    "SupplierPart",
    "ToolCall",
]
