"""Deterministic impact rules: raw ERP facts in, evaluated metrics out.

The module is intentionally pure:

- no database or Neo4j access;
- no call to the system clock — every rule that depends on time receives an
  explicit ``as_of_date``;
- every quantity is ``Decimal`` and every decision is a controlled enum.

Deciding what the numbers *mean* for the business (shortage, overall EOL risk,
which alternative to use) is deliberately out of scope: that is the cross-domain
orchestration of the next task.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from app.domain.dto.erp_facts import (
    InventoryFact,
    ProductionRequirementFact,
    PurchaseOrderFact,
    SalesOrderFact,
    SupplierFact,
)
from app.domain.dto.impact_metrics import (
    AlternativeAssessment,
    AlternativeClassification,
    InventoryMetrics,
    ProductionDemandClass,
    ProductionMetrics,
    ProductionRequirementAssessment,
    PurchaseInboundClass,
    PurchaseLineAssessment,
    PurchaseMetrics,
    PurchaseOrderAssessment,
    PurchaseTimingAssessment,
    PurchaseTimingClass,
    SalesExposureClass,
    SalesExposureMetrics,
    SalesLineAssessment,
    SalesMaterialEquivalentLine,
    SalesMaterialEquivalentMetrics,
    SalesOrderAssessment,
    SupplierEOLMetrics,
    SupplyCoverage,
)
from app.domain.dto.product_structure import AlternativeResult
from app.domain.errors import DomainValidationError

#: Purchase header states that count as committed open inbound material.
COMMITTED_PURCHASE_STATUSES: frozenset[str] = frozenset(
    {"OPEN", "PARTIALLY_RECEIVED"}
)

#: Purchase header states that only represent a possible inbound.
POTENTIAL_PURCHASE_STATUSES: frozenset[str] = frozenset({"DRAFT"})

#: Purchase header states that are blocked from becoming inbound.
BLOCKED_PURCHASE_STATUSES: frozenset[str] = frozenset({"BLOCKED"})

#: Purchase header states that no longer count as inbound.
CLOSED_PURCHASE_STATUSES: frozenset[str] = frozenset({"COMPLETED", "CANCELLED"})

#: Production order states that still need the component.
CURRENT_DEMAND_STATUSES: frozenset[str] = frozenset({"RELEASED", "IN_PROGRESS"})

#: Production order states whose demand is already history.
HISTORICAL_DEMAND_STATUSES: frozenset[str] = frozenset({"COMPLETED"})

#: Sales order states that expose the company right now.
CURRENT_EXPOSURE_STATUSES: frozenset[str] = frozenset(
    {"OPEN", "CONFIRMED", "PARTIALLY_DELIVERED"}
)

#: Sales order states that may expose the company later.
POTENTIAL_EXPOSURE_STATUSES: frozenset[str] = frozenset({"DRAFT"})

#: Sales order states that no longer expose the company.
NOT_EXPOSED_STATUSES: frozenset[str] = frozenset({"COMPLETED", "CANCELLED"})

#: Alternative qualification mapping (v0.4 section 21).
ALTERNATIVE_CLASSIFICATION: dict[str, AlternativeClassification] = {
    "QUALIFIED": AlternativeClassification.ELIGIBLE,
    "CONDITIONAL": AlternativeClassification.REQUIRES_REVIEW,
    "UNQUALIFIED": AlternativeClassification.INELIGIBLE,
}


def compute_supplier_eol_metrics(
    fact: SupplierFact, as_of_date: date
) -> SupplierEOLMetrics:
    """Return the EOL time metrics of one supply relationship.

    The deadline day itself still counts as actionable: ``last_time_buy_passed``
    becomes true only when ``as_of_date`` is strictly after the date.
    """
    days_to_ltb = (
        (fact.last_time_buy_date - as_of_date).days
        if fact.last_time_buy_date is not None
        else None
    )
    days_to_eol = (
        (fact.eol_date - as_of_date).days if fact.eol_date is not None else None
    )
    return SupplierEOLMetrics(
        part_number=fact.part_number,
        revision_code=fact.revision_code or "",
        supplier_code=fact.supplier_code,
        supplier_name=fact.supplier_name,
        supplier_part_status=fact.supplier_part_status,
        qualification_status=fact.qualification_status,
        as_of_date=as_of_date,
        last_time_buy_date=fact.last_time_buy_date,
        eol_date=fact.eol_date,
        days_to_last_time_buy=days_to_ltb,
        days_to_eol=days_to_eol,
        last_time_buy_passed=(
            fact.last_time_buy_date is not None and as_of_date > fact.last_time_buy_date
        ),
        eol_passed=fact.eol_date is not None and as_of_date > fact.eol_date,
    )


def compute_inventory_metrics(
    part_number: str,
    revision_code: str,
    facts: Sequence[InventoryFact],
) -> InventoryMetrics:
    """Sum the inventory of a part revision across all locations.

    Reservations may never exceed the physical stock (the database enforces it
    per row in v0.4 section 28), so a violating input is reported instead of
    being clipped to zero.
    """
    total_on_hand = Decimal(0)
    total_reserved = Decimal(0)
    locations: list[str] = []
    for fact in facts:
        if fact.qty_reserved > fact.qty_on_hand:
            raise DomainValidationError(
                "inventory fact violates the reserved <= on_hand invariant: "
                f"({fact.part_number}, {fact.revision_code}) at "
                f"{fact.plant_code}/{fact.warehouse_code} has "
                f"reserved={fact.qty_reserved} > on_hand={fact.qty_on_hand}"
            )
        total_on_hand += fact.qty_on_hand
        total_reserved += fact.qty_reserved
        location = f"{fact.plant_code}/{fact.warehouse_code}"
        if location not in locations:
            locations.append(location)

    available = total_on_hand - total_reserved
    if available < 0:
        raise DomainValidationError(
            f"available inventory is negative for ({part_number}, "
            f"{revision_code}): {available}"
        )
    return InventoryMetrics(
        part_number=part_number,
        revision_code=revision_code,
        total_on_hand=total_on_hand,
        total_reserved=total_reserved,
        available_qty=available,
        line_count=len(facts),
        locations=tuple(locations),
    )


def classify_purchase_status(status: str) -> PurchaseInboundClass:
    """Map a purchase order header status to its inbound class."""
    if status in COMMITTED_PURCHASE_STATUSES:
        return PurchaseInboundClass.COMMITTED_OPEN
    if status in POTENTIAL_PURCHASE_STATUSES:
        return PurchaseInboundClass.POTENTIAL
    if status in BLOCKED_PURCHASE_STATUSES:
        return PurchaseInboundClass.BLOCKED
    if status in CLOSED_PURCHASE_STATUSES:
        return PurchaseInboundClass.CLOSED
    raise DomainValidationError(
        f"unknown purchase order status: {status!r}; update the inbound rules "
        "before using this status"
    )


def compute_purchase_metrics(
    part_number: str,
    revision_code: str,
    facts: Sequence[PurchaseOrderFact],
) -> PurchaseMetrics:
    """Classify purchase order lines and sum their remaining quantities.

    The order header status decides the class; the line supplies the quantity.
    Arrival dates are carried as facts but not judged here.
    """
    lines: list[PurchaseLineAssessment] = []
    orders: dict[str, PurchaseOrderAssessment] = {}
    totals: dict[PurchaseInboundClass, Decimal] = {
        PurchaseInboundClass.COMMITTED_OPEN: Decimal(0),
        PurchaseInboundClass.POTENTIAL: Decimal(0),
        PurchaseInboundClass.BLOCKED: Decimal(0),
    }

    for fact in facts:
        if fact.received_qty > fact.ordered_qty:
            raise DomainValidationError(
                "purchase line violates the received <= ordered invariant: "
                f"{fact.po_number} line {fact.line_number} has "
                f"received={fact.received_qty} > ordered={fact.ordered_qty}"
            )
        classification = classify_purchase_status(fact.po_status)
        remaining = fact.ordered_qty - fact.received_qty
        lines.append(
            PurchaseLineAssessment(
                po_number=fact.po_number,
                po_status=fact.po_status,
                classification=classification,
                supplier_code=fact.supplier_code,
                line_number=fact.line_number,
                ordered_qty=fact.ordered_qty,
                received_qty=fact.received_qty,
                remaining_qty=remaining,
                currency=fact.currency,
                expected_date=fact.expected_date,
            )
        )
        totals[classification] = totals.get(classification, Decimal(0)) + remaining

        order = orders.get(fact.po_number)
        if order is None:
            orders[fact.po_number] = PurchaseOrderAssessment(
                po_number=fact.po_number,
                po_status=fact.po_status,
                classification=classification,
                supplier_code=fact.supplier_code,
                remaining_qty=remaining,
                line_count=1,
                expected_date=fact.po_expected_date,
            )
        else:
            orders[fact.po_number] = order.model_copy(
                update={
                    "remaining_qty": order.remaining_qty + remaining,
                    "line_count": order.line_count + 1,
                }
            )

    return PurchaseMetrics(
        part_number=part_number,
        revision_code=revision_code,
        committed_open_qty=totals[PurchaseInboundClass.COMMITTED_OPEN],
        potential_qty=totals[PurchaseInboundClass.POTENTIAL],
        blocked_qty=totals[PurchaseInboundClass.BLOCKED],
        lines=lines,
        orders=sorted(orders.values(), key=lambda item: item.po_number),
    )


def classify_production_status(status: str) -> ProductionDemandClass:
    """Map a production order status to its demand class.

    ``PLANNED`` orders have not been released, so a frozen requirement for them
    is a data consistency error rather than a demand (v0.4 section 64).
    """
    if status in CURRENT_DEMAND_STATUSES:
        return ProductionDemandClass.CURRENT_FROZEN_DEMAND
    if status in HISTORICAL_DEMAND_STATUSES:
        return ProductionDemandClass.HISTORICAL_DEMAND
    if status == "PLANNED":
        raise DomainValidationError(
            "PLANNED production order must not have a frozen material "
            "requirement: data consistency error"
        )
    raise DomainValidationError(
        f"unknown production order status: {status!r}; update the demand rules "
        "before using this status"
    )


def compute_production_metrics(
    part_number: str,
    revision_code: str,
    facts: Sequence[ProductionRequirementFact],
) -> ProductionMetrics:
    """Aggregate the frozen demand that still has to be satisfied.

    ``reserved_qty`` is kept as a fact and is *not* subtracted from the remaining
    quantity: a reservation is not a consumption.
    """
    assessments: list[ProductionRequirementAssessment] = []
    remaining_by_order: dict[str, Decimal] = {}
    remaining_by_product: dict[str, Decimal] = {}
    current_total = Decimal(0)
    current_orders: set[str] = set()
    historical_orders: set[str] = set()

    for fact in facts:
        if fact.issued_qty > fact.required_qty:
            raise DomainValidationError(
                "production requirement violates the issued <= required "
                f"invariant: {fact.order_number} line {fact.line_number} has "
                f"issued={fact.issued_qty} > required={fact.required_qty}"
            )
        classification = classify_production_status(fact.order_status)
        remaining = fact.required_qty - fact.issued_qty
        assessments.append(
            ProductionRequirementAssessment(
                order_number=fact.order_number,
                order_status=fact.order_status,
                classification=classification,
                product_part_number=fact.product_part_number,
                product_revision=fact.product_revision,
                line_number=fact.line_number,
                required_qty=fact.required_qty,
                reserved_qty=fact.reserved_qty,
                issued_qty=fact.issued_qty,
                remaining_required_qty=remaining,
                planned_start=fact.planned_start,
                planned_end=fact.planned_end,
            )
        )
        if classification is ProductionDemandClass.CURRENT_FROZEN_DEMAND:
            current_total += remaining
            current_orders.add(fact.order_number)
            remaining_by_order[fact.order_number] = (
                remaining_by_order.get(fact.order_number, Decimal(0)) + remaining
            )
            remaining_by_product[fact.product_part_number] = (
                remaining_by_product.get(fact.product_part_number, Decimal(0))
                + remaining
            )
        else:
            historical_orders.add(fact.order_number)

    return ProductionMetrics(
        part_number=part_number,
        revision_code=revision_code,
        current_remaining_qty=current_total,
        current_order_count=len(current_orders),
        historical_order_count=len(historical_orders),
        requirements=assessments,
        remaining_by_order=remaining_by_order,
        remaining_by_product=remaining_by_product,
    )


def classify_sales_status(status: str) -> SalesExposureClass:
    """Map a sales order header status to its exposure class."""
    if status in CURRENT_EXPOSURE_STATUSES:
        return SalesExposureClass.CURRENT_EXPOSURE
    if status in POTENTIAL_EXPOSURE_STATUSES:
        return SalesExposureClass.POTENTIAL_EXPOSURE
    if status in NOT_EXPOSED_STATUSES:
        return SalesExposureClass.NOT_EXPOSED
    raise DomainValidationError(
        f"unknown sales order status: {status!r}; update the exposure rules "
        "before using this status"
    )


def compute_sales_exposure_metrics(
    product_references: Sequence[tuple[str, str]],
    facts: Sequence[SalesOrderFact],
) -> SalesExposureMetrics:
    """Classify sales order lines and sum the open delivery quantities."""
    lines: list[SalesLineAssessment] = []
    orders: dict[str, SalesOrderAssessment] = {}
    current_orders: set[str] = set()
    potential_orders: set[str] = set()
    not_exposed_orders: set[str] = set()
    current_qty = Decimal(0)
    potential_qty = Decimal(0)

    for fact in facts:
        if fact.delivered_qty > fact.ordered_qty:
            raise DomainValidationError(
                "sales line violates the delivered <= ordered invariant: "
                f"{fact.order_number} line {fact.line_number} has "
                f"delivered={fact.delivered_qty} > ordered={fact.ordered_qty}"
            )
        classification = classify_sales_status(fact.order_status)
        remaining = fact.ordered_qty - fact.delivered_qty
        lines.append(
            SalesLineAssessment(
                order_number=fact.order_number,
                order_status=fact.order_status,
                classification=classification,
                customer_code=fact.customer_code,
                line_number=fact.line_number,
                product_part_number=fact.product_part_number,
                product_revision=fact.product_revision,
                ordered_qty=fact.ordered_qty,
                delivered_qty=fact.delivered_qty,
                remaining_delivery_qty=remaining,
                requested_delivery_date=fact.requested_delivery_date,
            )
        )
        if classification is SalesExposureClass.CURRENT_EXPOSURE:
            current_orders.add(fact.order_number)
            current_qty += remaining
        elif classification is SalesExposureClass.POTENTIAL_EXPOSURE:
            potential_orders.add(fact.order_number)
            potential_qty += remaining
        else:
            not_exposed_orders.add(fact.order_number)

        order = orders.get(fact.order_number)
        if order is None:
            orders[fact.order_number] = SalesOrderAssessment(
                order_number=fact.order_number,
                order_status=fact.order_status,
                classification=classification,
                customer_code=fact.customer_code,
                remaining_delivery_qty=remaining,
                line_count=1,
                requested_delivery_date=fact.requested_delivery_date,
            )
        else:
            orders[fact.order_number] = order.model_copy(
                update={
                    "remaining_delivery_qty": (
                        order.remaining_delivery_qty + remaining
                    ),
                    "line_count": order.line_count + 1,
                }
            )

    return SalesExposureMetrics(
        product_references=tuple(
            (number, revision) for number, revision in product_references
        ),
        current_exposure_orders=len(current_orders),
        current_exposure_qty=current_qty,
        potential_exposure_orders=len(potential_orders),
        potential_exposure_qty=potential_qty,
        not_exposed_orders=len(not_exposed_orders),
        lines=lines,
        orders=sorted(orders.values(), key=lambda item: item.order_number),
    )


def classify_qualification_status(status: str) -> AlternativeClassification:
    """Map an alternative qualification to its assessment class."""
    try:
        return ALTERNATIVE_CLASSIFICATION[status]
    except KeyError as exc:
        raise DomainValidationError(
            f"unknown alternative qualification status: {status!r}; update the "
            "qualification rules before using this status"
        ) from exc


def assess_alternatives(result: AlternativeResult) -> list[AlternativeAssessment]:
    """Classify the alternatives of a part revision.

    The result only states the qualification class; it never selects one.
    """
    return [
        AlternativeAssessment(
            alternative_part_number=row.alternative_part_number,
            alternative_revision_code=row.alternative_revision_code,
            qualification_status=row.qualification_status,
            replacement_type=row.replacement_type,
            classification=classify_qualification_status(row.qualification_status),
            verified_by=row.verified_by,
            verified_at=row.verified_at,
        )
        for row in result.rows
    ]


def classify_purchase_timing(
    expected_date: date | None,
    last_time_buy_date: date | None,
    eol_date: date | None,
) -> PurchaseTimingClass | None:
    """Classify a planned delivery date against the supplier EOL window.

    Boundaries follow the project's closed-interval business date rule: a
    delivery planned exactly on the last-time-buy date still arrives before it,
    and one planned exactly on the EOL date is still before EOL.

    Returns ``None`` when no EOL window is known (nothing can be classified) and
    ``EXPECTED_DATE_UNKNOWN`` when a window exists but the line has no date.
    """
    if eol_date is None:
        return None
    if expected_date is None:
        return PurchaseTimingClass.EXPECTED_DATE_UNKNOWN
    if last_time_buy_date is not None and expected_date <= last_time_buy_date:
        return PurchaseTimingClass.ARRIVES_BEFORE_LTB
    if expected_date <= eol_date:
        return PurchaseTimingClass.ARRIVES_AFTER_LTB_BEFORE_EOL
    return PurchaseTimingClass.ARRIVES_AFTER_EOL


def assess_purchase_timing(
    metrics: PurchaseMetrics,
    last_time_buy_date: date | None,
    eol_date: date | None,
) -> list[PurchaseTimingAssessment]:
    """Add the deterministic timing class to every purchase line.

    Every line is returned, including closed ones, so the caller keeps the full
    evidence set; the timing class only describes the planned date.
    """
    return [
        PurchaseTimingAssessment(
            po_number=line.po_number,
            line_number=line.line_number,
            po_status=line.po_status,
            classification=line.classification,
            ordered_qty=line.ordered_qty,
            received_qty=line.received_qty,
            remaining_qty=line.remaining_qty,
            expected_date=line.expected_date,
            timing_classification=classify_purchase_timing(
                line.expected_date, last_time_buy_date, eol_date
            ),
        )
        for line in metrics.lines
    ]


def compute_sales_material_equivalent(
    exposure: SalesExposureMetrics,
    requirement_per_product: Mapping[str, Decimal],
) -> SalesMaterialEquivalentMetrics:
    """Convert sales exposure into the equivalent quantity of the affected part.

    ``requirement_per_product`` maps a finished product number to the quantity of
    the affected part needed for one unit of that product (the ``totals`` of the
    BOM explosion). The result must not be added to the frozen production demand:
    the model has no sales-order to production-order allocation, so summing them
    would count the same material twice.
    """
    lines: list[SalesMaterialEquivalentLine] = []
    current_total = Decimal(0)
    potential_total = Decimal(0)

    for line in exposure.lines:
        requirement = requirement_per_product.get(line.product_part_number)
        if requirement is None:
            raise DomainValidationError(
                "missing per-product requirement for "
                f"{line.product_part_number!r}; every affected product needs a "
                "BOM explosion quantity before material equivalents are computed"
            )
        equivalent = line.remaining_delivery_qty * requirement
        lines.append(
            SalesMaterialEquivalentLine(
                order_number=line.order_number,
                line_number=line.line_number,
                order_status=line.order_status,
                classification=line.classification,
                product_part_number=line.product_part_number,
                product_revision=line.product_revision,
                remaining_delivery_qty=line.remaining_delivery_qty,
                requirement_per_product=requirement,
                material_equivalent_qty=equivalent,
            )
        )
        if line.classification is SalesExposureClass.CURRENT_EXPOSURE:
            current_total += equivalent
        elif line.classification is SalesExposureClass.POTENTIAL_EXPOSURE:
            potential_total += equivalent

    return SalesMaterialEquivalentMetrics(
        current_material_equivalent_qty=current_total,
        potential_material_equivalent_qty=potential_total,
        lines=lines,
    )


def compute_supply_coverage(
    available_inventory: Decimal,
    committed_open_purchase_qty: Decimal,
    current_frozen_production_demand: Decimal,
) -> SupplyCoverage:
    """Compare stored and committed material with the current frozen demand.

    ``projected`` includes committed open purchase quantities as facts; it does
    **not** assert that those deliveries will actually happen on time.
    """
    inventory_delta = available_inventory - current_frozen_production_demand
    projected_delta = (
        available_inventory
        + committed_open_purchase_qty
        - current_frozen_production_demand
    )
    return SupplyCoverage(
        available_inventory=available_inventory,
        current_frozen_production_demand=current_frozen_production_demand,
        committed_open_purchase_qty=committed_open_purchase_qty,
        inventory_coverage_delta=inventory_delta,
        projected_coverage_delta=projected_delta,
        inventory_covers_current_frozen_demand=inventory_delta >= 0,
        projected_supply_covers_current_frozen_demand=projected_delta >= 0,
    )
