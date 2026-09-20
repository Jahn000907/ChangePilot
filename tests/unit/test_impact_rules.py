"""Unit tests for the pure impact rules (no database involved)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.domain.dto.erp_facts import (
    InventoryFact,
    ProductionRequirementFact,
    PurchaseOrderFact,
    SalesOrderFact,
    SupplierFact,
)
from app.domain.dto.impact_metrics import (
    AlternativeClassification,
    ProductionDemandClass,
    PurchaseInboundClass,
    SalesExposureClass,
)
from app.domain.dto.product_structure import AlternativeResult, AlternativeRow
from app.domain.errors import DomainValidationError
from app.domain.rules.impact import (
    assess_alternatives,
    classify_purchase_status,
    classify_qualification_status,
    classify_sales_status,
    compute_inventory_metrics,
    compute_production_metrics,
    compute_purchase_metrics,
    compute_sales_exposure_metrics,
    compute_supplier_eol_metrics,
)
from tests.fixtures.erp_fact_fakes import (
    inventory_fact,
    production_requirement_fact,
    purchase_line_fact,
    sales_line_fact,
    supplier_part_fact,
)

AS_OF = date(2026, 9, 20)


def supplier_dto(**updates) -> SupplierFact:
    """Return a supplier DTO with optional field overrides."""
    return SupplierFact.model_validate(supplier_part_fact()).model_copy(
        update=updates
    )


def inventory_dto(on_hand: str = "820", reserved: str = "120", **updates):
    """Return an inventory DTO with Decimal quantities."""
    return InventoryFact.model_validate(
        inventory_fact(on_hand, reserved)
    ).model_copy(update=updates)


def purchase_dto(
    po_number: str, status: str, ordered: str = "500", received: str = "0", **updates
) -> PurchaseOrderFact:
    """Return a purchase line DTO."""
    return PurchaseOrderFact.model_validate(
        purchase_line_fact(po_number, status, ordered, received)
    ).model_copy(update=updates)


def production_dto(
    order: str,
    status: str,
    required: str = "60",
    issued: str = "0",
    product: str = "ROB-P100",
    **updates,
) -> ProductionRequirementFact:
    """Return a frozen requirement DTO."""
    return ProductionRequirementFact.model_validate(
        production_requirement_fact(order, status)
    ).model_copy(
        update={
            "required_qty": Decimal(required),
            "issued_qty": Decimal(issued),
            "product_part_number": product,
            **updates,
        }
    )


def sales_dto(
    order: str,
    status: str,
    ordered: str = "6",
    delivered: str = "0",
    product: str = "ROB-P100",
    **updates,
) -> SalesOrderFact:
    """Return a sales line DTO."""
    return SalesOrderFact.model_validate(
        sales_line_fact(order, status, product)
    ).model_copy(
        update={
            "ordered_qty": Decimal(ordered),
            "delivered_qty": Decimal(delivered),
            **updates,
        }
    )


# ---------------------------------------------------------------------------
# Supplier EOL metrics
# ---------------------------------------------------------------------------
def test_supplier_metrics_count_down_to_ltb_and_eol():
    """The golden scenario dates produce the expected remaining days."""
    metrics = compute_supplier_eol_metrics(supplier_dto(), AS_OF)

    assert metrics.days_to_last_time_buy == 71  # 2026-09-20 -> 2026-11-30
    assert metrics.days_to_eol == 133  # 2026-09-20 -> 2027-01-31
    assert metrics.last_time_buy_passed is False
    assert metrics.eol_passed is False
    assert metrics.as_of_date == AS_OF


def test_supplier_metrics_on_the_deadline_day():
    """The deadline day itself is still actionable."""
    metrics = compute_supplier_eol_metrics(
        supplier_dto(), date(2026, 11, 30)
    )

    assert metrics.days_to_last_time_buy == 0
    assert metrics.last_time_buy_passed is False


def test_supplier_metrics_after_the_deadline():
    """The day after the deadline the window is reported as passed."""
    metrics = compute_supplier_eol_metrics(supplier_dto(), date(2026, 12, 1))

    assert metrics.days_to_last_time_buy == -1
    assert metrics.last_time_buy_passed is True
    assert metrics.eol_passed is False


def test_supplier_metrics_without_dates():
    """Missing dates give no countdown and are never "passed"."""
    metrics = compute_supplier_eol_metrics(
        supplier_dto(last_time_buy_date=None, eol_date=None), AS_OF
    )

    assert metrics.days_to_last_time_buy is None
    assert metrics.days_to_eol is None
    assert metrics.last_time_buy_passed is False
    assert metrics.eol_passed is False


# ---------------------------------------------------------------------------
# Inventory metrics
# ---------------------------------------------------------------------------
def test_inventory_metrics_compute_available_quantity():
    """820 on hand minus 120 reserved leaves 700 available, in Decimal."""
    metrics = compute_inventory_metrics(
        "BRG-6204-A", "A", [inventory_dto()]
    )

    assert metrics.total_on_hand == Decimal(820)
    assert metrics.total_reserved == Decimal(120)
    assert metrics.available_qty == Decimal(700)
    assert isinstance(metrics.available_qty, Decimal)
    assert metrics.line_count == 1
    assert metrics.locations == ("CN-E01/WH-01",)


def test_inventory_metrics_aggregate_multiple_locations():
    """Several plants / warehouses are summed into one available quantity."""
    metrics = compute_inventory_metrics(
        "BRG-6204-A",
        "A",
        [
            inventory_dto("820", "120"),
            inventory_dto("180", "30", warehouse_code="WH-02"),
        ],
    )

    assert metrics.total_on_hand == Decimal(1000)
    assert metrics.total_reserved == Decimal(150)
    assert metrics.available_qty == Decimal(850)
    assert metrics.line_count == 2
    assert metrics.locations == ("CN-E01/WH-01", "CN-E01/WH-02")


def test_inventory_metrics_reject_reserved_above_on_hand():
    """A row that breaks the database invariant is reported, not clipped."""
    with pytest.raises(DomainValidationError):
        compute_inventory_metrics("BRG-6204-A", "A", [inventory_dto("100", "300")])


def test_inventory_metrics_without_facts_are_zero():
    """No inventory is an empty fact set, not an error."""
    metrics = compute_inventory_metrics("BRG-6204-A", "A", [])

    assert metrics.available_qty == Decimal(0)
    assert metrics.line_count == 0
    assert metrics.locations == ()


# ---------------------------------------------------------------------------
# Purchase metrics
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("OPEN", PurchaseInboundClass.COMMITTED_OPEN),
        ("PARTIALLY_RECEIVED", PurchaseInboundClass.COMMITTED_OPEN),
        ("DRAFT", PurchaseInboundClass.POTENTIAL),
        ("BLOCKED", PurchaseInboundClass.BLOCKED),
        ("COMPLETED", PurchaseInboundClass.CLOSED),
        ("CANCELLED", PurchaseInboundClass.CLOSED),
    ],
)
def test_purchase_status_classification(status, expected):
    """Every documented purchase status maps to exactly one class."""
    assert classify_purchase_status(status) is expected


def test_purchase_metrics_sum_the_golden_seed_orders():
    """500-0 + (300-100) + (200-0) commits 900 units of open inbound."""
    metrics = compute_purchase_metrics(
        "BRG-6204-A",
        "A",
        [
            purchase_dto("PO-2026-000001", "OPEN", "500", "0"),
            purchase_dto("PO-2026-000004", "PARTIALLY_RECEIVED", "300", "100"),
            purchase_dto("PO-2026-000007", "OPEN", "200", "0"),
        ],
    )

    assert metrics.committed_open_qty == Decimal(900)
    assert metrics.potential_qty == Decimal(0)
    assert metrics.blocked_qty == Decimal(0)
    assert [order.po_number for order in metrics.orders] == [
        "PO-2026-000001",
        "PO-2026-000004",
        "PO-2026-000007",
    ]
    assert all(
        order.classification is PurchaseInboundClass.COMMITTED_OPEN
        for order in metrics.orders
    )
    assert isinstance(metrics.committed_open_qty, Decimal)


def test_purchase_metrics_separate_potential_and_blocked_inbound():
    """Draft and blocked orders are counted in their own buckets."""
    metrics = compute_purchase_metrics(
        "BRG-6204-A",
        "A",
        [
            purchase_dto("PO-A", "DRAFT", "50", "0"),
            purchase_dto("PO-B", "BLOCKED", "30", "0"),
            purchase_dto("PO-C", "COMPLETED", "20", "20"),
            purchase_dto("PO-D", "CANCELLED", "10", "0"),
        ],
    )

    assert metrics.committed_open_qty == Decimal(0)
    assert metrics.potential_qty == Decimal(50)
    assert metrics.blocked_qty == Decimal(30)
    assert metrics.potential_qty + metrics.blocked_qty == Decimal(80)


def test_purchase_metrics_reject_received_above_ordered():
    """A line that received more than ordered is a data error."""
    with pytest.raises(DomainValidationError):
        compute_purchase_metrics(
            "BRG-6204-A", "A", [purchase_dto("PO-X", "OPEN", "100", "150")]
        )


def test_purchase_metrics_reject_unknown_status():
    """An unrecognised purchase status must not be silently classified."""
    with pytest.raises(DomainValidationError):
        compute_purchase_metrics(
            "BRG-6204-A", "A", [purchase_dto("PO-X", "UNKNOWN", "10", "0")]
        )


# ---------------------------------------------------------------------------
# Production metrics
# ---------------------------------------------------------------------------
def test_production_metrics_sum_current_frozen_demand():
    """Released and in-progress orders contribute required minus issued."""
    metrics = compute_production_metrics(
        "BRG-6204-A",
        "A",
        [
            production_dto("MO-1", "RELEASED", "60", "0"),
            production_dto("MO-2", "IN_PROGRESS", "40", "10"),
            production_dto("MO-3", "COMPLETED", "25", "25"),
        ],
    )

    assert metrics.current_remaining_qty == Decimal(90)  # 60 + 30
    assert metrics.current_order_count == 2
    assert metrics.historical_order_count == 1
    assert metrics.remaining_by_order == {"MO-1": Decimal(60), "MO-2": Decimal(30)}
    assert metrics.remaining_by_product == {"ROB-P100": Decimal(90)}
    assert isinstance(metrics.current_remaining_qty, Decimal)


def test_production_metrics_keep_reserved_as_a_fact():
    """Reserved quantity is not subtracted from the remaining requirement."""
    metrics = compute_production_metrics(
        "BRG-6204-A",
        "A",
        [production_dto("MO-1", "RELEASED", "60", "0", reserved_qty=Decimal(20))],
    )

    assert metrics.requirements[0].reserved_qty == Decimal(20)
    assert metrics.requirements[0].remaining_required_qty == Decimal(60)
    assert metrics.current_remaining_qty == Decimal(60)


def test_production_metrics_reject_planned_frozen_requirement():
    """A PLANNED order must never carry a frozen requirement."""
    with pytest.raises(DomainValidationError):
        compute_production_metrics(
            "BRG-6204-A", "A", [production_dto("MO-11", "PLANNED", "6", "0")]
        )


def test_production_metrics_reject_unknown_status():
    """An unrecognised production status is a rule gap, not a demand."""
    with pytest.raises(DomainValidationError):
        compute_production_metrics(
            "BRG-6204-A", "A", [production_dto("MO-X", "WAITING", "6", "0")]
        )


def test_production_metrics_reject_issued_above_required():
    """Issued quantity cannot exceed the frozen requirement."""
    with pytest.raises(DomainValidationError):
        compute_production_metrics(
            "BRG-6204-A", "A", [production_dto("MO-X", "RELEASED", "10", "20")]
        )


# ---------------------------------------------------------------------------
# Sales exposure
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("OPEN", SalesExposureClass.CURRENT_EXPOSURE),
        ("CONFIRMED", SalesExposureClass.CURRENT_EXPOSURE),
        ("PARTIALLY_DELIVERED", SalesExposureClass.CURRENT_EXPOSURE),
        ("DRAFT", SalesExposureClass.POTENTIAL_EXPOSURE),
        ("COMPLETED", SalesExposureClass.NOT_EXPOSED),
        ("CANCELLED", SalesExposureClass.NOT_EXPOSED),
    ],
)
def test_sales_status_classification(status, expected):
    """Every documented sales status maps to exactly one exposure class."""
    assert classify_sales_status(status) is expected


def test_sales_exposure_metrics_aggregate_by_class():
    """Current, potential and not-exposed orders are separated."""
    metrics = compute_sales_exposure_metrics(
        [("ROB-P100", "A"), ("PAL-P300", "A")],
        [
            sales_dto("SO-1", "OPEN", "6", "0"),
            sales_dto("SO-2", "CONFIRMED", "3", "0", product="PAL-P300"),
            sales_dto("SO-3", "PARTIALLY_DELIVERED", "4", "1"),
            sales_dto("SO-4", "DRAFT", "1", "0"),
            sales_dto("SO-5", "COMPLETED", "5", "5"),
            sales_dto("SO-6", "CANCELLED", "2", "0"),
        ],
    )

    assert metrics.current_exposure_orders == 3
    assert metrics.current_exposure_qty == Decimal(12)  # 6 + 3 + 3
    assert metrics.potential_exposure_orders == 1
    assert metrics.potential_exposure_qty == Decimal(1)
    assert metrics.not_exposed_orders == 2
    assert metrics.product_references == (("ROB-P100", "A"), ("PAL-P300", "A"))
    assert isinstance(metrics.current_exposure_qty, Decimal)


def test_sales_exposure_metrics_reject_unknown_status():
    """An unrecognised sales status is a rule gap, not an exposure."""
    with pytest.raises(DomainValidationError):
        compute_sales_exposure_metrics(
            [("ROB-P100", "A")], [sales_dto("SO-X", "PENDING", "1", "0")]
        )


def test_sales_exposure_metrics_reject_delivered_above_ordered():
    """Delivered quantity cannot exceed the ordered quantity."""
    with pytest.raises(DomainValidationError):
        compute_sales_exposure_metrics(
            [("ROB-P100", "A")], [sales_dto("SO-X", "OPEN", "1", "2")]
        )


# ---------------------------------------------------------------------------
# Alternative qualification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("QUALIFIED", AlternativeClassification.ELIGIBLE),
        ("CONDITIONAL", AlternativeClassification.REQUIRES_REVIEW),
        ("UNQUALIFIED", AlternativeClassification.INELIGIBLE),
    ],
)
def test_qualification_classification(status, expected):
    """Qualification maps to eligibility without any preference."""
    assert classify_qualification_status(status) is expected


def test_qualification_classification_rejects_unknown_status():
    """An unrecognised qualification must not be guessed."""
    with pytest.raises(DomainValidationError):
        classify_qualification_status("MAYBE")


def test_alternative_assessment_has_no_recommendation():
    """The assessment classifies; it never selects an alternative."""
    result = AlternativeResult(
        part_number="BRG-6204-A",
        revision_code="A",
        rows=[
            AlternativeRow(
                alternative_part_number="BRG-6204-B",
                alternative_revision_code="A",
                qualification_status="QUALIFIED",
                replacement_type="DIRECT",
                verified_at=datetime(2026, 9, 1, tzinfo=UTC),
                verified_by="quality.engineer",
                alternative_id="alt-1",
            ),
            AlternativeRow(
                alternative_part_number="BRG-6204-C",
                alternative_revision_code="A",
                qualification_status="UNQUALIFIED",
                replacement_type="CONDITIONAL",
                verified_at=None,
                verified_by=None,
                alternative_id="alt-2",
            ),
        ],
    )

    assessments = assess_alternatives(result)

    assert [item.classification for item in assessments] == [
        AlternativeClassification.ELIGIBLE,
        AlternativeClassification.INELIGIBLE,
    ]
    fields = set(assessments[0].model_dump())
    assert not fields & {"recommended", "best_alternative", "selected"}
    assert ProductionDemandClass.CURRENT_FROZEN_DEMAND.value == (
        "CURRENT_FROZEN_DEMAND"
    )
