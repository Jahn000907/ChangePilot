"""Unit tests for :class:`ERPFactService` (no database involved)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.errors import DomainValidationError
from app.services.erp_facts import ERPFactService
from tests.fixtures.erp_fact_fakes import (
    FakeInventoryRepository,
    FakeProductionRepository,
    FakePurchaseRepository,
    FakeSalesRepository,
    FakeSupplierRepository,
    inventory_fact,
    production_requirement_fact,
    purchase_line_fact,
    sales_line_fact,
    supplier_part_fact,
)


def build_service(**repositories) -> ERPFactService:
    """Return a service wired with the supplied fakes."""
    return ERPFactService(**repositories)


def test_supplier_facts_preserve_supply_details():
    """Supplier facts keep qualification, status and the LTB / EOL dates."""
    repository = FakeSupplierRepository(facts=[supplier_part_fact()])

    result = build_service(suppliers=repository).supplier_parts("BRG-TEST-A", "A")

    assert repository.calls == [("BRG-TEST-A", "A")]
    row = result.rows[0]
    assert row.supplier_code == "SUP-TEST-1"
    assert row.supplier_part_status == "LAST_TIME_BUY"
    assert row.qualification_status == "QUALIFIED"
    assert row.last_time_buy_date.isoformat() == "2026-11-30"
    assert row.eol_date.isoformat() == "2027-01-31"
    assert isinstance(row.unit_price, Decimal)
    assert isinstance(row.minimum_order_qty, Decimal)


def test_inventory_facts_stay_decimal_and_pass_filters():
    """Inventory quantities stay ``Decimal`` and filters are forwarded."""
    repository = FakeInventoryRepository(facts=[inventory_fact()])

    result = build_service(inventory=repository).inventory(
        "BRG-TEST-A", "A", plant_code="CN-E01", warehouse_code="WH-01"
    )

    assert repository.calls == [("BRG-TEST-A", "A", "CN-E01", "WH-01")]
    row = result.rows[0]
    assert row.qty_on_hand == Decimal(820)
    assert row.qty_reserved == Decimal(120)
    assert isinstance(row.qty_on_hand, Decimal)
    assert isinstance(row.unit_cost, Decimal)
    assert not hasattr(row, "available_qty")  # rule layer owns that value


def test_purchase_facts_keep_statuses_and_quantities():
    """Purchase facts return order/line statuses and ordered/received amounts."""
    repository = FakePurchaseRepository(
        facts=[
            purchase_line_fact("PO-TEST-1", "OPEN", "500", "0"),
            purchase_line_fact("PO-TEST-2", "PARTIALLY_RECEIVED", "300", "100"),
        ]
    )

    result = build_service(purchase=repository).purchase_order_lines(
        "BRG-TEST-A", "A"
    )

    assert [row.po_status for row in result.rows] == ["OPEN", "PARTIALLY_RECEIVED"]
    assert result.rows[1].ordered_qty == Decimal(300)
    assert result.rows[1].received_qty == Decimal(100)
    assert all(isinstance(row.ordered_qty, Decimal) for row in result.rows)


def test_production_facts_forward_status_filter():
    """Production facts forward the optional order status filter."""
    repository = FakeProductionRepository(
        facts=[production_requirement_fact("MO-TEST-1", "RELEASED")]
    )

    result = build_service(production=repository).production_requirements(
        "BRG-TEST-A", "A", order_statuses=["RELEASED", "IN_PROGRESS"]
    )

    assert repository.calls == [
        ("BRG-TEST-A", "A", ("RELEASED", "IN_PROGRESS")),
    ]
    assert result.order_statuses == ("RELEASED", "IN_PROGRESS")
    assert result.rows[0].required_qty == Decimal("60.0000")
    assert isinstance(result.rows[0].reserved_qty, Decimal)


def test_sales_facts_normalise_product_references():
    """Sales references are validated, de-duplicated and forwarded."""
    repository = FakeSalesRepository(facts=[sales_line_fact()])

    result = build_service(sales=repository).sales_order_lines(
        [("ROB-TEST", "A"), ("ROB-TEST", "A"), ("PAL-TEST", "A")]
    )

    assert repository.calls == [(("ROB-TEST", "A"), ("PAL-TEST", "A"))]
    assert result.product_references == (("ROB-TEST", "A"), ("PAL-TEST", "A"))
    assert result.rows[0].ordered_qty == Decimal(6)
    assert result.rows[0].delivered_qty == Decimal(0)


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("supplier_parts", ("   ", "A")),
        ("supplier_parts", ("BRG-TEST-A", "")),
        ("inventory", ("BRG-TEST-A", "  ")),
        ("purchase_order_lines", ("", "A")),
        ("production_requirements", ("BRG-TEST-A", "\t")),
    ],
)
def test_blank_identifiers_are_rejected(method, args):
    """Blank identifiers fail validation before touching the repository."""
    service = build_service(
        suppliers=FakeSupplierRepository(),
        inventory=FakeInventoryRepository(),
        purchase=FakePurchaseRepository(),
        production=FakeProductionRepository(),
    )

    with pytest.raises(DomainValidationError):
        getattr(service, method)(*args)


def test_blank_plant_or_warehouse_filter_is_rejected():
    """An explicitly passed but blank filter is a caller mistake."""
    service = build_service(inventory=FakeInventoryRepository())

    with pytest.raises(DomainValidationError):
        service.inventory("BRG-TEST-A", "A", plant_code="  ")
    with pytest.raises(DomainValidationError):
        service.inventory("BRG-TEST-A", "A", warehouse_code="")


@pytest.mark.parametrize(
    "references",
    [
        [],
        "ROB-TEST",
        [("ROB-TEST",)],
        [("ROB-TEST", "A", "extra")],
        [("", "A")],
    ],
)
def test_invalid_product_references_are_rejected(references):
    """An empty or malformed affected-product list is a caller mistake."""
    service = build_service(sales=FakeSalesRepository())

    with pytest.raises(DomainValidationError):
        service.sales_order_lines(references)


def test_order_status_filter_must_be_a_sequence():
    """A bare string is not a valid status list."""
    service = build_service(production=FakeProductionRepository())

    with pytest.raises(DomainValidationError):
        service.production_requirements("BRG-TEST-A", "A", order_statuses="RELEASED")


def test_empty_results_are_not_errors():
    """"No inventory" or "no purchase order" is an empty result, not a failure."""
    service = build_service(
        suppliers=FakeSupplierRepository(),
        inventory=FakeInventoryRepository(),
        purchase=FakePurchaseRepository(),
        production=FakeProductionRepository(),
        sales=FakeSalesRepository(),
    )

    assert service.supplier_parts("BRG-UNKNOWN", "A").rows == []
    assert service.inventory("BRG-UNKNOWN", "A").rows == []
    assert service.purchase_order_lines("BRG-UNKNOWN", "A").rows == []
    assert service.production_requirements("BRG-UNKNOWN", "A").rows == []
    assert service.sales_order_lines([("ROB-UNKNOWN", "A")]).rows == []


def test_dto_boundary_has_no_orm_types():
    """DTOs only expose plain python types and never an ORM row."""
    service = build_service(
        suppliers=FakeSupplierRepository(facts=[supplier_part_fact()]),
        inventory=FakeInventoryRepository(facts=[inventory_fact()]),
    )

    supplier_payload = service.supplier_parts("BRG-TEST-A", "A").model_dump()
    inventory_payload = service.inventory("BRG-TEST-A", "A").model_dump()

    for payload in (supplier_payload, inventory_payload):
        assert isinstance(payload, dict)
        text = repr(payload)
        assert "sqlalchemy" not in text
        assert "Row" not in text
        assert "Decimal('" in text  # amounts stay decimal, not float
