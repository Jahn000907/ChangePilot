"""Read-only tools backed by :class:`ERPFactService`."""

from __future__ import annotations

from app.domain.dto.erp_facts import (
    InventoryFactResult,
    ProductionRequirementFactResult,
    PurchaseOrderFactResult,
)
from app.domain.errors import DomainError
from app.services.erp_facts import ERPFactService
from app.tools.schemas import (
    GetInventoryInput,
    GetProductionRequirementsInput,
    GetPurchaseOrdersInput,
)


class ERPFactToolError(RuntimeError):
    """An ERP fact tool failed outside controlled domain errors."""


def get_inventory(
    request: GetInventoryInput,
    *,
    service: ERPFactService | None = None,
) -> InventoryFactResult:
    """Return stored inventory facts for one part revision."""
    active_service = service if service is not None else ERPFactService()
    try:
        return active_service.inventory(
            part_number=request.part_number,
            revision_code=request.revision_code,
            plant_code=request.plant_code,
            warehouse_code=request.warehouse_code,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise ERPFactToolError("inventory query failed") from exc


def get_purchase_orders(
    request: GetPurchaseOrdersInput,
    *,
    service: ERPFactService | None = None,
) -> PurchaseOrderFactResult:
    """Return purchase-order line facts for one part revision."""
    active_service = service if service is not None else ERPFactService()
    try:
        return active_service.purchase_order_lines(
            part_number=request.part_number,
            revision_code=request.revision_code,
            open_only=request.open_only,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise ERPFactToolError("purchase order query failed") from exc


def get_production_requirements(
    request: GetProductionRequirementsInput,
    *, service: ERPFactService | None = None,
) -> ProductionRequirementFactResult:
    active_service = service if service is not None else ERPFactService()
    try:
        return active_service.production_requirements(
            part_number=request.part_number,
            revision_code=request.revision_code,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise ERPFactToolError("production requirement query failed") from exc
