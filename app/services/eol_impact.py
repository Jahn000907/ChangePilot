"""Supplier EOL impact analysis: cross-domain orchestration.

This service is the first complete ChangePilot business capability. It composes
the already existing layers instead of reimplementing them:

    ProductStructureService (Neo4j: where-used, BOM explosion, alternatives)
              +
    ERPFactService         (PostgreSQL: supplier, inventory, purchase,
                            production, sales facts)
              +
    app.domain.rules.impact (deterministic calculations and classifications)
              ↓
    SupplierEOLImpactResult

It writes no Cypher and no SQLAlchemy query, repeats no metric formula, and reads
no system clock: the caller supplies ``as_of_date`` and the same date is passed to
every query and every rule.

The result deliberately stops at structured facts: there is no overall risk
score, no recommended strategy and no chosen alternative.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.domain.dto.eol_impact import (
    IMPACT_CAVEATS,
    AlternativeImpact,
    BOMQuantityEvidence,
    BOMQuantityImpact,
    InventoryImpact,
    ProductImpact,
    ProductionImpact,
    PurchaseImpact,
    SalesImpact,
    SupplierEOLImpactResult,
    SupplierImpact,
    WhereUsedPathEvidence,
)
from app.domain.dto.impact_metrics import (
    AlternativeClassification,
    ProductionDemandClass,
    PurchaseTimingClass,
    SupplierEOLMetrics,
)
from app.domain.errors import DomainValidationError
from app.domain.rules.impact import (
    assess_alternatives,
    assess_purchase_timing,
    compute_inventory_metrics,
    compute_production_metrics,
    compute_purchase_metrics,
    compute_sales_exposure_metrics,
    compute_sales_material_equivalent,
    compute_supplier_eol_metrics,
    compute_supply_coverage,
)
from app.services.erp_facts import ERPFactService
from app.services.product_structure import DEFAULT_MAX_DEPTH, ProductStructureService

#: Part type that marks a finished product in the product structure graph.
FINISHED_PRODUCT_TYPE = "FINISHED_PRODUCT"


class EOLImpactService:
    """Produce a deterministic Supplier EOL impact analysis."""

    def __init__(
        self,
        product_structure: ProductStructureService | None = None,
        erp_facts: ERPFactService | None = None,
    ) -> None:
        self._product_structure = (
            product_structure if product_structure is not None else ProductStructureService()
        )
        self._erp_facts = erp_facts if erp_facts is not None else ERPFactService()

    @property
    def product_structure(self) -> ProductStructureService:
        """Return the product structure service used for the analysis."""
        return self._product_structure

    @property
    def erp_facts(self) -> ERPFactService:
        """Return the ERP fact service used for the analysis."""
        return self._erp_facts

    def analyze_supplier_eol(
        self,
        part_number: str,
        revision_code: str,
        as_of_date: date,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> SupplierEOLImpactResult:
        """Analyse the impact of a supplier EOL for one part revision.

        ``as_of_date`` is mandatory: the analysis must never silently depend on
        the machine clock.
        """
        part_number = _require_identifier(part_number, "part_number")
        revision_code = _require_identifier(revision_code, "revision_code")
        effective_date = _require_as_of_date(as_of_date)

        # ------------------------------------------------------------------
        # 1. product structure: where is the part used?
        # ------------------------------------------------------------------
        where_used = self._product_structure.where_used(
            part_number, revision_code, max_depth=max_depth, as_of_date=effective_date
        )
        revision_of_product: dict[str, str] = {}
        for row in where_used.rows:
            if row.ancestor_part_type == FINISHED_PRODUCT_TYPE:
                revision_of_product[row.ancestor_part_number] = (
                    row.ancestor_revision_code
                )
        product_impact = ProductImpact(
            part_number=part_number,
            revision_code=revision_code,
            as_of_date=effective_date,
            max_depth=max_depth,
            direct_parent_assemblies=sorted(
                {
                    row.ancestor_part_number
                    for row in where_used.rows
                    if row.bom_level == 1
                }
            ),
            affected_assemblies=sorted(
                {
                    row.ancestor_part_number
                    for row in where_used.rows
                    if row.ancestor_part_type != FINISHED_PRODUCT_TYPE
                }
            ),
            affected_finished_products=sorted(revision_of_product),
            paths=[
                WhereUsedPathEvidence(
                    ancestor_part_number=row.ancestor_part_number,
                    ancestor_revision_code=row.ancestor_revision_code,
                    ancestor_part_type=row.ancestor_part_type,
                    bom_level=row.bom_level,
                    path=list(row.path),
                    bom_version_id=row.bom_version_id,
                    bom_code=row.bom_code,
                )
                for row in where_used.rows
            ],
        )

        # ------------------------------------------------------------------
        # 2. how much of the part does each affected product need?
        # ------------------------------------------------------------------
        requirement_per_product: dict[str, Decimal] = {}
        bom_evidence: list[BOMQuantityEvidence] = []
        products_without_requirement: list[str] = []
        for product in product_impact.affected_finished_products:
            product_revision = revision_of_product[product]
            explosion = self._product_structure.explode_bom(
                product,
                product_revision,
                max_depth=max_depth,
                as_of_date=effective_date,
            )
            requirement = explosion.quantity_of(part_number, revision_code)
            requirement_per_product[product] = requirement
            if requirement <= 0:
                products_without_requirement.append(product)
            bom_evidence.append(
                BOMQuantityEvidence(
                    product_part_number=product,
                    product_revision=product_revision,
                    requirement_per_product=requirement,
                    bom_version_id=explosion.bom_version_id,
                    bom_code=explosion.bom_code,
                )
            )
        bom_quantity_impact = BOMQuantityImpact(
            part_number=part_number,
            revision_code=revision_code,
            as_of_date=effective_date,
            requirement_per_product=requirement_per_product,
            evidence=bom_evidence,
            products_without_requirement=products_without_requirement,
        )

        # ------------------------------------------------------------------
        # 3. supplier side (all relationships are kept)
        # ------------------------------------------------------------------
        supplier_metrics = [
            compute_supplier_eol_metrics(fact, effective_date)
            for fact in self._erp_facts.supplier_parts(part_number, revision_code).rows
        ]
        reference = _reference_supplier(supplier_metrics)
        supplier_impact = SupplierImpact(
            suppliers=supplier_metrics,
            reference_supplier_code=(
                reference.supplier_code if reference is not None else None
            ),
            reference_last_time_buy_date=(
                reference.last_time_buy_date if reference is not None else None
            ),
            reference_eol_date=(
                reference.eol_date if reference is not None else None
            ),
        )

        # ------------------------------------------------------------------
        # 4. inventory / purchase / production facts through the 2C rules
        # ------------------------------------------------------------------
        inventory_metrics = compute_inventory_metrics(
            part_number,
            revision_code,
            self._erp_facts.inventory(part_number, revision_code).rows,
        )
        inventory_impact = InventoryImpact(
            part_number=part_number,
            revision_code=revision_code,
            total_on_hand=inventory_metrics.total_on_hand,
            total_reserved=inventory_metrics.total_reserved,
            available_qty=inventory_metrics.available_qty,
            line_count=inventory_metrics.line_count,
            locations=inventory_metrics.locations,
        )

        purchase_metrics = compute_purchase_metrics(
            part_number,
            revision_code,
            self._erp_facts.purchase_order_lines(part_number, revision_code).rows,
        )
        timing_assessments = assess_purchase_timing(
            purchase_metrics,
            supplier_impact.reference_last_time_buy_date,
            supplier_impact.reference_eol_date,
        )
        timing_counts: dict[str, int] = {
            timing_class.value: 0 for timing_class in PurchaseTimingClass
        }
        timing_counts["NO_EOL_WINDOW"] = 0
        for assessment in timing_assessments:
            key = (
                assessment.timing_classification.value
                if assessment.timing_classification is not None
                else "NO_EOL_WINDOW"
            )
            timing_counts[key] = timing_counts.get(key, 0) + 1
        purchase_impact = PurchaseImpact(
            part_number=part_number,
            revision_code=revision_code,
            committed_open_qty=purchase_metrics.committed_open_qty,
            potential_qty=purchase_metrics.potential_qty,
            blocked_qty=purchase_metrics.blocked_qty,
            reference_last_time_buy_date=supplier_impact.reference_last_time_buy_date,
            reference_eol_date=supplier_impact.reference_eol_date,
            orders=purchase_metrics.orders,
            lines=timing_assessments,
            timing_counts=timing_counts,
        )

        production_facts = self._erp_facts.production_requirements(
            part_number, revision_code
        ).rows
        production_metrics = compute_production_metrics(
            part_number, revision_code, production_facts
        )
        reserved_by_order: dict[str, Decimal] = {}
        for fact in production_facts:
            reserved_by_order[fact.order_number] = (
                reserved_by_order.get(fact.order_number, Decimal(0))
                + fact.reserved_qty
            )
        production_impact = ProductionImpact(
            part_number=part_number,
            revision_code=revision_code,
            current_frozen_demand_qty=production_metrics.current_remaining_qty,
            current_orders=sorted(production_metrics.remaining_by_order),
            historical_orders=sorted(
                {
                    assessment.order_number
                    for assessment in production_metrics.requirements
                    if assessment.classification
                    is ProductionDemandClass.HISTORICAL_DEMAND
                }
            ),
            remaining_by_order=production_metrics.remaining_by_order,
            remaining_by_product=production_metrics.remaining_by_product,
            reserved_by_order=reserved_by_order,
        )

        # ------------------------------------------------------------------
        # 5. sales exposure of the affected finished products
        # ------------------------------------------------------------------
        product_references = tuple(
            (product, revision_of_product[product])
            for product in product_impact.affected_finished_products
        )
        sales_facts = (
            self._erp_facts.sales_order_lines(list(product_references)).rows
            if product_references
            else []
        )
        exposure = compute_sales_exposure_metrics(product_references, sales_facts)
        material_equivalent = compute_sales_material_equivalent(
            exposure, requirement_per_product
        )
        sales_impact = SalesImpact(
            product_references=product_references,
            current_exposure_orders=exposure.current_exposure_orders,
            current_exposure_qty=exposure.current_exposure_qty,
            potential_exposure_orders=exposure.potential_exposure_orders,
            potential_exposure_qty=exposure.potential_exposure_qty,
            not_exposed_orders=exposure.not_exposed_orders,
            lines=exposure.lines,
            material_equivalent=material_equivalent,
        )

        # ------------------------------------------------------------------
        # 6. alternative qualification (classification only)
        # ------------------------------------------------------------------
        assessments = assess_alternatives(
            self._product_structure.find_alternatives(part_number, revision_code)
        )
        alternative_impact = AlternativeImpact(
            assessments=assessments,
            eligible_count=sum(
                1
                for item in assessments
                if item.classification is AlternativeClassification.ELIGIBLE
            ),
            requires_review_count=sum(
                1
                for item in assessments
                if item.classification is AlternativeClassification.REQUIRES_REVIEW
            ),
            ineligible_count=sum(
                1
                for item in assessments
                if item.classification is AlternativeClassification.INELIGIBLE
            ),
        )

        # ------------------------------------------------------------------
        # 7. coverage of the frozen demand by stored / committed material
        # ------------------------------------------------------------------
        coverage = compute_supply_coverage(
            available_inventory=inventory_impact.available_qty,
            committed_open_purchase_qty=purchase_impact.committed_open_qty,
            current_frozen_production_demand=(
                production_impact.current_frozen_demand_qty
            ),
        )

        return SupplierEOLImpactResult(
            part_number=part_number,
            revision_code=revision_code,
            as_of_date=effective_date,
            supplier=supplier_impact,
            product=product_impact,
            bom_quantity=bom_quantity_impact,
            inventory=inventory_impact,
            purchase=purchase_impact,
            production=production_impact,
            sales=sales_impact,
            alternatives=alternative_impact,
            coverage=coverage,
            caveats=IMPACT_CAVEATS,
        )


def _reference_supplier(
    metrics: list[SupplierEOLMetrics],
) -> SupplierEOLMetrics | None:
    """Return the supplier relationship that defines the EOL window.

    The window with the earliest EOL date drives the analysis. This is a data
    fact used for date classification, not a ranking of suppliers.
    """
    candidates = [item for item in metrics if item.eol_date is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item.eol_date, item.supplier_code))


def _require_identifier(value: str, field: str) -> str:
    """Return a trimmed identifier or raise a domain validation error."""
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _require_as_of_date(value: date) -> date:
    """Return the business date of the analysis, validating its type."""
    if isinstance(value, datetime):
        raise DomainValidationError(
            "as_of_date must be a date, not a datetime: " f"{value.isoformat()}"
        )
    if not isinstance(value, date):
        raise DomainValidationError(
            f"as_of_date must be a date, got {type(value).__name__}"
        )
    return value
