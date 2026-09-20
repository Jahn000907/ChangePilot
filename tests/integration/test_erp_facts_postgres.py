"""Integration tests for the ERP fact queries against the golden seed.

These tests need the Docker PostgreSQL instance with the loaded golden seed.
When the database is unreachable, or the seed is missing, they skip with a clear
reason instead of failing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.postgres.session import create_session
from app.services.erp_facts import ERPFactService

EOL_PART = "BRG-6204-A"
PRODUCT_REFERENCES = (
    ("ROB-P100", "A"),
    ("ROB-P200", "A"),
    ("CON-C100", "A"),
    ("PAL-P300", "A"),
)


@pytest.fixture(scope="module")
def service() -> ERPFactService:
    """Return a service bound to the golden seed, skipping without PostgreSQL."""
    try:
        with create_session() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    erp = ERPFactService()
    if not erp.supplier_parts(EOL_PART, "A").rows:
        pytest.skip("golden seed is not loaded (BRG-6204-A has no supply row)")
    return erp


def test_supplier_facts_for_the_eol_bearing(service):
    """MotionWorks supplies BRG-6204-A as a last-time-buy with an EOL date."""
    result = service.supplier_parts(EOL_PART, "A")

    row = next(item for item in result.rows if item.supplier_code == "SUP-001")
    assert row.supplier_name == "MotionWorks"
    assert row.supplier_status == "ACTIVE"
    assert row.supplier_part_status == "LAST_TIME_BUY"
    assert row.qualification_status == "QUALIFIED"
    assert row.last_time_buy_date.isoformat() == "2026-11-30"
    assert row.eol_date.isoformat() == "2027-01-31"
    assert row.unit_price == Decimal("12.5000")
    assert row.lead_time_days == 30
    assert row.minimum_order_qty == Decimal(50)
    assert isinstance(row.unit_price, Decimal)


def test_supplier_facts_distinguish_qualified_and_unqualified_alternatives(service):
    """The candidate replacements differ in price, lead time and qualification."""
    qualified = service.supplier_parts("BRG-6204-B", "A").rows
    unqualified = service.supplier_parts("BRG-6204-C", "A").rows

    assert qualified[0].qualification_status == "QUALIFIED"
    assert unqualified[0].qualification_status == "UNQUALIFIED"
    assert qualified[0].unit_price > unqualified[0].unit_price
    assert qualified[0].lead_time_days > unqualified[0].lead_time_days
    assert qualified[0].supplier_code == unqualified[0].supplier_code == "SUP-001"


def test_inventory_facts_for_the_eol_bearing(service):
    """The stored balance is read exactly, with Decimal quantities."""
    result = service.inventory(EOL_PART, "A", plant_code="CN-E01", warehouse_code="WH-01")

    assert len(result.rows) == 1
    row = result.rows[0]
    assert (row.plant_code, row.warehouse_code) == ("CN-E01", "WH-01")
    assert row.qty_on_hand == Decimal(820)
    assert row.qty_reserved == Decimal(120)
    assert isinstance(row.qty_on_hand, Decimal)
    assert isinstance(row.unit_cost, Decimal)


def test_inventory_filter_that_matches_nothing_is_empty(service):
    """A filter that matches no warehouse yields an empty result, not an error."""
    result = service.inventory(EOL_PART, "A", warehouse_code="WH-99")

    assert result.rows == []
    assert result.warehouse_code == "WH-99"


def test_purchase_facts_include_the_three_unfinished_orders(service):
    """The unfinished purchase orders and their quantities are visible."""
    result = service.purchase_order_lines(EOL_PART, "A")

    by_po = {row.po_number: row for row in result.rows}
    assert by_po["PO-2026-000001"].po_status == "OPEN"
    assert by_po["PO-2026-000001"].ordered_qty == Decimal(500)
    assert by_po["PO-2026-000001"].received_qty == Decimal(0)
    assert by_po["PO-2026-000004"].po_status == "PARTIALLY_RECEIVED"
    assert by_po["PO-2026-000004"].ordered_qty == Decimal(300)
    assert by_po["PO-2026-000004"].received_qty == Decimal(100)
    assert by_po["PO-2026-000007"].po_status == "OPEN"
    assert by_po["PO-2026-000007"].ordered_qty == Decimal(200)
    assert all(row.supplier_code == "SUP-001" for row in result.rows)
    assert all(row.received_qty <= row.ordered_qty for row in result.rows)
    assert all(isinstance(row.ordered_qty, Decimal) for row in result.rows)


def test_production_requirements_come_from_frozen_facts(service):
    """Frozen requirements are read per order; PLANNED orders have none."""
    result = service.production_requirements(EOL_PART, "A")

    statuses = {row.order_status for row in result.rows}
    assert {"RELEASED", "IN_PROGRESS", "COMPLETED"} <= statuses
    assert "MO-2026-000011" not in {row.order_number for row in result.rows}
    assert all(row.required_qty > 0 for row in result.rows)
    assert all(row.issued_qty <= row.required_qty for row in result.rows)

    mo_1 = next(row for row in result.rows if row.order_number == "MO-2026-000001")
    assert mo_1.required_qty == Decimal("60.0000")
    assert mo_1.product_part_number == "ROB-P100"

    unfinished = service.production_requirements(
        EOL_PART, "A", order_statuses=["RELEASED", "IN_PROGRESS"]
    )
    unfinished_orders = {row.order_number for row in unfinished.rows}
    assert len(unfinished_orders) == 9
    assert unfinished.order_statuses == ("RELEASED", "IN_PROGRESS")


def test_sales_facts_cover_the_affected_products(service):
    """Sales facts are queried per affected product, with all statuses."""
    result = service.sales_order_lines(list(PRODUCT_REFERENCES))

    statuses = {row.order_status for row in result.rows}
    assert {
        "OPEN",
        "CONFIRMED",
        "PARTIALLY_DELIVERED",
        "DRAFT",
        "COMPLETED",
        "CANCELLED",
    } <= statuses
    assert {row.product_part_number for row in result.rows} <= {
        number for number, _revision in PRODUCT_REFERENCES
    }
    assert all(row.delivered_qty <= row.ordered_qty for row in result.rows)
    assert all(isinstance(row.ordered_qty, Decimal) for row in result.rows)
    # Sub-assembly sales lines are not part of the affected product set.
    assert all(
        row.product_part_number.startswith(("ROB-", "CON-", "PAL-"))
        for row in result.rows
    )


def test_unknown_part_returns_empty_results(service):
    """An unknown part yields empty fact sets, never a domain error."""
    assert service.supplier_parts("PART-NOT-IN-SEED", "A").rows == []
    assert service.inventory("PART-NOT-IN-SEED", "A").rows == []
    assert service.purchase_order_lines("PART-NOT-IN-SEED", "A").rows == []
    assert service.production_requirements("PART-NOT-IN-SEED", "A").rows == []
    assert service.sales_order_lines([("ROB-NOT-IN-SEED", "A")]).rows == []
