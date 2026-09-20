"""ChangePilot application services."""

from __future__ import annotations

from app.services.eol_impact import EOLImpactService
from app.services.erp_facts import ERPFactService
from app.services.product_structure import (
    DEFAULT_MAX_DEPTH,
    MAX_ALLOWED_DEPTH,
    ProductStructureService,
)

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "MAX_ALLOWED_DEPTH",
    "EOLImpactService",
    "ERPFactService",
    "ProductStructureService",
]
