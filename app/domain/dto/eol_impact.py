"""DTOs of the Supplier EOL impact analysis.

The result is a bundle of deterministic facts, metrics and rule classifications
produced by the cross-domain orchestration service. It contains:

- no overall risk score and no recommended action — those would compress
  multi-dimensional facts into an unvalidated judgement;
- no LLM-generated text: the only prose is a fixed tuple of caveats that the
  code itself defines;
- no Neo4j / SQLAlchemy object — every value is a plain python type, ``Decimal``
  or ``date``.

Evidence identifiers are kept so a later agent step can cite deterministic
sources: purchase order and line numbers, production order numbers, sales order
and line numbers, affected part revisions with their BOM path and version.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.dto.impact_metrics import (
    AlternativeAssessment,
    PurchaseOrderAssessment,
    PurchaseTimingAssessment,
    SalesLineAssessment,
    SalesMaterialEquivalentMetrics,
    SupplierEOLMetrics,
    SupplyCoverage,
)


class _ImpactModel(BaseModel):
    """Base model shared by the impact analysis result."""

    model_config = ConfigDict(from_attributes=True)


class SupplierImpact(_ImpactModel):
    """Supplier side of the analysis.

    Every supply relationship is kept; the reference window is the earliest EOL
    window that drives the analysis. It is a data fact, not a supplier ranking.
    """

    suppliers: list[SupplierEOLMetrics]
    reference_supplier_code: str | None = None
    reference_last_time_buy_date: date | None = None
    reference_eol_date: date | None = None


class WhereUsedPathEvidence(_ImpactModel):
    """One traversed BOM path from the affected part up to an ancestor."""

    ancestor_part_number: str
    ancestor_revision_code: str
    ancestor_part_type: str
    bom_level: int = Field(ge=1)
    path: list[str]
    bom_version_id: str
    bom_code: str


class ProductImpact(_ImpactModel):
    """Where-used view of the affected product structure."""

    part_number: str
    revision_code: str
    as_of_date: date
    max_depth: int
    direct_parent_assemblies: list[str]
    affected_assemblies: list[str]
    affected_finished_products: list[str]
    paths: list[WhereUsedPathEvidence]


class BOMQuantityEvidence(_ImpactModel):
    """Explosion evidence for one affected product."""

    product_part_number: str
    product_revision: str
    requirement_per_product: Decimal
    bom_version_id: str
    bom_code: str


class BOMQuantityImpact(_ImpactModel):
    """Per-product requirement of the affected part.

    The quantities come from the ``totals`` of the BOM explosion, which sum every
    path per single product unit.
    """

    part_number: str
    revision_code: str
    as_of_date: date
    requirement_per_product: dict[str, Decimal]
    evidence: list[BOMQuantityEvidence]
    products_without_requirement: list[str]


class InventoryImpact(_ImpactModel):
    """Stored inventory of the affected part."""

    part_number: str
    revision_code: str
    total_on_hand: Decimal
    total_reserved: Decimal
    available_qty: Decimal
    line_count: int = Field(ge=0)
    locations: tuple[str, ...] = ()


class PurchaseImpact(_ImpactModel):
    """Purchase inbound facts with their planned-delivery timing class."""

    part_number: str
    revision_code: str
    committed_open_qty: Decimal
    potential_qty: Decimal
    blocked_qty: Decimal
    reference_last_time_buy_date: date | None = None
    reference_eol_date: date | None = None
    orders: list[PurchaseOrderAssessment]
    lines: list[PurchaseTimingAssessment]
    timing_counts: dict[str, int]


class ProductionImpact(_ImpactModel):
    """Frozen production demand read from PostgreSQL, never recomputed."""

    part_number: str
    revision_code: str
    current_frozen_demand_qty: Decimal
    current_orders: list[str]
    historical_orders: list[str]
    remaining_by_order: dict[str, Decimal]
    remaining_by_product: dict[str, Decimal]
    reserved_by_order: dict[str, Decimal]


class SalesImpact(_ImpactModel):
    """Customer exposure and its material-equivalent view."""

    product_references: tuple[tuple[str, str], ...]
    current_exposure_orders: int = Field(ge=0)
    current_exposure_qty: Decimal
    potential_exposure_orders: int = Field(ge=0)
    potential_exposure_qty: Decimal
    not_exposed_orders: int = Field(ge=0)
    lines: list[SalesLineAssessment]
    material_equivalent: SalesMaterialEquivalentMetrics


class AlternativeImpact(_ImpactModel):
    """Qualification classification of the alternatives (no recommendation)."""

    assessments: list[AlternativeAssessment]
    eligible_count: int = Field(ge=0)
    requires_review_count: int = Field(ge=0)
    ineligible_count: int = Field(ge=0)


class SupplierEOLImpactResult(_ImpactModel):
    """Complete deterministic Supplier EOL impact analysis."""

    part_number: str
    revision_code: str
    as_of_date: date
    supplier: SupplierImpact
    product: ProductImpact
    bom_quantity: BOMQuantityImpact
    inventory: InventoryImpact
    purchase: PurchaseImpact
    production: ProductionImpact
    sales: SalesImpact
    alternatives: AlternativeImpact
    coverage: SupplyCoverage
    #: Fixed, code-owned statements about how the numbers may be used.
    caveats: tuple[str, ...] = ()

    @property
    def affected_product_numbers(self) -> list[str]:
        """Return the affected finished product numbers."""
        return list(self.product.affected_finished_products)


#: Statements the result carries so downstream consumers cannot misread it.
IMPACT_CAVEATS: tuple[str, ...] = (
    "projected_coverage_delta 只反映已承诺的开放采购事实，不代表货物一定会按计划到货。",
    (
        "sales.material_equivalent 是销售侧结构等价暴露，不得与 production 冻结需求相加，"
        "当前模型没有销售订单到生产订单的分配关系。"
    ),
    "purchase.lines[].timing_classification 只描述计划日期落在 EOL 窗口的哪个区间。",
    "结果不包含综合风险评分与处置建议，这些由后续 Planner / Reviewer 基于事实形成。",
)
