"""Read-only application tool for deterministic Supplier EOL analysis."""

from __future__ import annotations

from app.domain.dto.eol_impact import SupplierEOLImpactResult
from app.domain.errors import DomainError
from app.services.eol_impact import EOLImpactService
from app.tools.schemas import SupplierEOLImpactInput


class SupplierEOLImpactToolError(RuntimeError):
    """The Supplier EOL tool failed outside the controlled domain errors."""


def analyze_supplier_eol(
    request: SupplierEOLImpactInput,
    *,
    service: EOLImpactService | None = None,
) -> SupplierEOLImpactResult:
    """Run the existing Supplier EOL service through a stable tool contract.

    The default service uses the project's shared Neo4j driver and short-lived
    PostgreSQL sessions. An injected service is supported for focused tests and
    future application composition without introducing a dependency framework.

    Domain validation and not-found errors remain typed domain errors. Unknown
    infrastructure failures are translated so callers do not depend on a
    SQLAlchemy or Neo4j exception type.
    """
    active_service = service if service is not None else EOLImpactService()
    try:
        return active_service.analyze_supplier_eol(
            part_number=request.part_number,
            revision_code=request.revision_code,
            as_of_date=request.as_of_date,
            max_depth=request.max_depth,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise SupplierEOLImpactToolError(
            "supplier EOL impact analysis failed"
        ) from exc
