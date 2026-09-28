"""Read-only tools backed by :class:`ProductStructureService`."""

from __future__ import annotations

from app.domain.dto.product_structure import (
    AlternativeResult,
    BomExplosionResult,
    WhereUsedResult,
)
from app.domain.errors import DomainError
from app.services.product_structure import ProductStructureService
from app.tools.schemas import (
    FindWhereUsedInput,
    GetAlternativesInput,
    GetBOMStructureInput,
)


class ProductStructureToolError(RuntimeError):
    """A product structure tool failed outside controlled domain errors."""


def get_bom_structure(
    request: GetBOMStructureInput,
    *,
    service: ProductStructureService | None = None,
) -> BomExplosionResult:
    """Return the effective BOM explosion for one part revision."""
    active_service = service if service is not None else ProductStructureService()
    try:
        return active_service.explode_bom(
            part_number=request.part_number,
            revision_code=request.revision_code,
            max_depth=request.max_depth,
            as_of_date=request.as_of_date,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise ProductStructureToolError("BOM structure query failed") from exc


def find_where_used(
    request: FindWhereUsedInput,
    *,
    service: ProductStructureService | None = None,
) -> WhereUsedResult:
    """Return effective parent assemblies and products for one part revision."""
    active_service = service if service is not None else ProductStructureService()
    try:
        return active_service.where_used(
            part_number=request.part_number,
            revision_code=request.revision_code,
            max_depth=request.max_depth,
            as_of_date=request.as_of_date,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise ProductStructureToolError("where-used query failed") from exc


def get_alternatives(
    request: GetAlternativesInput,
    *,
    service: ProductStructureService | None = None,
) -> AlternativeResult:
    """Return alternative-part facts without selecting a replacement."""
    active_service = service if service is not None else ProductStructureService()
    try:
        return active_service.find_alternatives(
            part_number=request.part_number,
            revision_code=request.revision_code,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise ProductStructureToolError("alternative query failed") from exc
