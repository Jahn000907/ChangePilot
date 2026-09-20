"""Integration test: real golden seed facts evaluated by the impact rules.

The test wires the real services (Neo4j product structure + PostgreSQL ERP
facts) into the pure rule layer and checks the accepted CASE-EOL-001 numbers.
It skips when either database is unreachable or the seed is missing.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from neo4j.exceptions import Neo4jError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.neo4j.driver import close_driver, get_driver
from app.db.postgres.session import create_session
from app.domain.dto.impact_metrics import (
    AlternativeClassification,
    InventoryMetrics,
    ProductionMetrics,
    PurchaseInboundClass,
    SalesExposureClass,
    SalesExposureMetrics,
    SupplierEOLMetrics,
)
from app.domain.rules.impact import (
    assess_alternatives,
    compute_inventory_metrics,
    compute_production_metrics,
    compute_purchase_metrics,
    compute_sales_exposure_metrics,
    compute_supplier_eol_metrics,
)
from app.services.erp_facts import ERPFactService
from app.services.product_structure import ProductStructureService

EOL_PART = "BRG-6204-A"
REVISION = "A"
AS_OF = date(2026, 9, 20)
PRODUCT_REFERENCES = (
    ("ROB-P100", "A"),
    ("ROB-P200", "A"),
    ("CON-C100", "A"),
    ("PAL-P300", "A"),
)


@dataclass(frozen=True)
class GoldenMetrics:
    """Every rule-layer result of the golden scenario."""

    supplier: SupplierEOLMetrics
    inventory: InventoryMetrics
    purchase: object
    production: ProductionMetrics
    sales: SalesExposureMetrics
    alternatives: list


@pytest.fixture(scope="module")
def metrics() -> Iterator[GoldenMetrics]:
    """Return the rule-layer results computed from the real seed."""
    try:
        get_driver().verify_connectivity()
    except (Neo4jError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"Neo4j is not reachable: {exc}")
    try:
        with create_session() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    erp = ERPFactService()
    supplier_rows = erp.supplier_parts(EOL_PART, REVISION).rows
    if not supplier_rows:
        close_driver()
        pytest.skip("golden seed is not loaded")

    product_structure = ProductStructureService()
    alternatives = product_structure.find_alternatives(EOL_PART, REVISION)

    result = GoldenMetrics(
        supplier=compute_supplier_eol_metrics(
            next(row for row in supplier_rows if row.supplier_code == "SUP-001"),
            AS_OF,
        ),
        inventory=compute_inventory_metrics(
            EOL_PART, REVISION, erp.inventory(EOL_PART, REVISION).rows
        ),
        purchase=compute_purchase_metrics(
            EOL_PART, REVISION, erp.purchase_order_lines(EOL_PART, REVISION).rows
        ),
        production=compute_production_metrics(
            EOL_PART, REVISION, erp.production_requirements(EOL_PART, REVISION).rows
        ),
        sales=compute_sales_exposure_metrics(
            PRODUCT_REFERENCES,
            erp.sales_order_lines([("ROB-P100", "A"), ("ROB-P200", "A"),
                                   ("CON-C100", "A"), ("PAL-P300", "A")]).rows,
        ),
        alternatives=assess_alternatives(alternatives),
    )
    yield result
    close_driver()


def test_supplier_eol_metrics_on_the_golden_scenario(metrics):
    """LTB / EOL dates and the countdown match the accepted scenario."""
    assert metrics.supplier.last_time_buy_date.isoformat() == "2026-11-30"
    assert metrics.supplier.eol_date.isoformat() == "2027-01-31"
    assert metrics.supplier.days_to_last_time_buy == 71
    assert metrics.supplier.days_to_eol == 133
    assert metrics.supplier.last_time_buy_passed is False
    assert metrics.supplier.eol_passed is False


def test_inventory_metrics_on_the_golden_scenario(metrics):
    """The stored balance yields 700 available units in Decimal."""
    assert metrics.inventory.total_on_hand == Decimal(820)
    assert metrics.inventory.total_reserved == Decimal(120)
    assert metrics.inventory.available_qty == Decimal(700)
    assert isinstance(metrics.inventory.available_qty, Decimal)


def test_purchase_metrics_on_the_golden_scenario(metrics):
    """The three unfinished purchase orders commit 900 units."""
    assert metrics.purchase.committed_open_qty == Decimal(900)
    assert metrics.purchase.potential_qty == Decimal(0)
    assert metrics.purchase.blocked_qty == Decimal(0)
    assert {order.po_number for order in metrics.purchase.orders} == {
        "PO-2026-000001",
        "PO-2026-000004",
        "PO-2026-000007",
    }
    assert all(
        order.classification is PurchaseInboundClass.COMMITTED_OPEN
        for order in metrics.purchase.orders
    )


def test_production_metrics_on_the_golden_scenario(metrics):
    """Frozen demand still to be satisfied totals 322 units."""
    assert metrics.production.current_remaining_qty == Decimal(322)
    assert metrics.production.current_order_count == 9
    assert "MO-2026-000011" not in metrics.production.remaining_by_order
    assert set(metrics.production.remaining_by_product) <= {
        "ROB-P100",
        "ROB-P200",
        "CON-C100",
        "PAL-P300",
    }


def test_sales_exposure_metrics_on_the_golden_scenario(metrics):
    """Eleven current orders expose 31 units; one draft order exposes 1."""
    assert metrics.sales.current_exposure_orders == 11
    assert metrics.sales.current_exposure_qty == Decimal(31)
    assert metrics.sales.potential_exposure_orders == 1
    assert metrics.sales.potential_exposure_qty == Decimal(1)
    assert all(
        order.classification
        in {SalesExposureClass.CURRENT_EXPOSURE, SalesExposureClass.POTENTIAL_EXPOSURE}
        for order in metrics.sales.orders
        if order.order_status not in {"COMPLETED", "CANCELLED"}
    )


def test_alternative_assessment_on_the_golden_scenario(metrics):
    """B is eligible, C is ineligible; nothing is recommended."""
    by_part = {
        item.alternative_part_number: item for item in metrics.alternatives
    }
    assert (
        by_part["BRG-6204-B"].classification
        is AlternativeClassification.ELIGIBLE
    )
    assert (
        by_part["BRG-6204-C"].classification
        is AlternativeClassification.INELIGIBLE
    )
    assert not {"recommended", "best_alternative"} & set(
        by_part["BRG-6204-B"].model_dump()
    )
