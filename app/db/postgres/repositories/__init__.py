"""ChangePilot PostgreSQL repositories."""

from __future__ import annotations

from app.db.postgres.repositories.base import ReadOnlyRepository
from app.db.postgres.repositories.ecm import (
    ChangeCaseRecord,
    ChangeImpactRecord,
    ChangeStrategyActionRecord,
    ChangeStrategyRecord,
    ECMRepository,
    EngineeringChangeOrderRecord,
    EngineeringChangeRequestRecord,
    ExecutionJobRecord,
)
from app.db.postgres.repositories.inventory import InventoryFact, InventoryRepository
from app.db.postgres.repositories.production import (
    ProductionRepository,
    ProductionRequirementFact,
)
from app.db.postgres.repositories.purchase import (
    PurchaseOrderLineFact,
    PurchaseRepository,
)
from app.db.postgres.repositories.sales import (
    SalesOrderLineFact,
    SalesRepository,
)
from app.db.postgres.repositories.supplier import SupplierPartFact, SupplierRepository
from app.db.postgres.repositories.trace import TraceRepository

__all__ = [
    "ChangeCaseRecord",
    "ChangeImpactRecord",
    "ChangeStrategyActionRecord",
    "ChangeStrategyRecord",
    "ECMRepository",
    "EngineeringChangeOrderRecord",
    "EngineeringChangeRequestRecord",
    "ExecutionJobRecord",
    "InventoryFact",
    "InventoryRepository",
    "ProductionRepository",
    "ProductionRequirementFact",
    "PurchaseOrderLineFact",
    "PurchaseRepository",
    "ReadOnlyRepository",
    "SalesOrderLineFact",
    "SalesRepository",
    "SupplierPartFact",
    "SupplierRepository",
    "TraceRepository",
]
