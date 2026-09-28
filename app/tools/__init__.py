"""Stable application tools exposed to future API, MCP and agent adapters."""

from __future__ import annotations

from app.domain.dto.eol_impact import SupplierEOLImpactResult
from app.domain.dto.erp_facts import InventoryFactResult, PurchaseOrderFactResult
from app.domain.dto.product_structure import (
    AlternativeResult,
    BomExplosionResult,
    WhereUsedResult,
)
from app.tools.eol_impact import SupplierEOLImpactToolError, analyze_supplier_eol
from app.tools.erp_facts import ERPFactToolError, get_inventory, get_purchase_orders
from app.tools.langchain import get_review_tools
from app.tools.product_structure import (
    ProductStructureToolError,
    find_where_used,
    get_alternatives,
    get_bom_structure,
)
from app.tools.schemas import (
    FindWhereUsedInput,
    GetAlternativesInput,
    GetBOMStructureInput,
    GetInventoryInput,
    GetPurchaseOrdersInput,
    SupplierEOLImpactInput,
)

__all__ = [
    "AlternativeResult",
    "BomExplosionResult",
    "ERPFactToolError",
    "FindWhereUsedInput",
    "GetAlternativesInput",
    "GetBOMStructureInput",
    "GetInventoryInput",
    "GetPurchaseOrdersInput",
    "InventoryFactResult",
    "ProductStructureToolError",
    "PurchaseOrderFactResult",
    "SupplierEOLImpactInput",
    "SupplierEOLImpactResult",
    "SupplierEOLImpactToolError",
    "WhereUsedResult",
    "analyze_supplier_eol",
    "find_where_used",
    "get_alternatives",
    "get_bom_structure",
    "get_inventory",
    "get_purchase_orders",
    "get_review_tools",
]
