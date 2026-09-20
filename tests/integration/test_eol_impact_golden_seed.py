"""Integration acceptance: the full Supplier EOL analysis on the golden seed.

Skips when either database is unreachable or the seed is missing.
"""

from __future__ import annotations

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
    PurchaseTimingClass,
)
from app.domain.errors import EntityNotFoundError
from app.services.eol_impact import EOLImpactService

EOL_PART = "BRG-6204-A"
REVISION = "A"
AS_OF = date(2026, 9, 20)
PRODUCTS = ("ROB-P100", "ROB-P200", "CON-C100", "PAL-P300")


@pytest.fixture(scope="module")
def result():
    """Run the complete analysis once for the module."""
    try:
        get_driver().verify_connectivity()
    except (Neo4jError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"Neo4j is not reachable: {exc}")
    try:
        with create_session() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    service = EOLImpactService()
    try:
        analysis = service.analyze_supplier_eol(EOL_PART, REVISION, AS_OF)
    except EntityNotFoundError as exc:  # pragma: no cover - seed dependent
        close_driver()
        pytest.skip(f"golden seed is not loaded: {exc}")
    yield analysis
    close_driver()


def test_supplier_impact(result):
    """MotionWorks supplies the part with the accepted EOL window."""
    reference = next(
        item for item in result.supplier.suppliers if item.supplier_code == "SUP-001"
    )
    assert reference.supplier_name == "MotionWorks"
    assert reference.supplier_part_status == "LAST_TIME_BUY"
    assert reference.last_time_buy_date.isoformat() == "2026-11-30"
    assert reference.eol_date.isoformat() == "2027-01-31"
    assert reference.days_to_last_time_buy == 71
    assert reference.days_to_eol == 133
    assert result.supplier.reference_supplier_code == "SUP-001"


def test_product_and_bom_quantity_impact(result):
    """Four products are affected with the accepted per-product quantities."""
    assert set(result.product.affected_finished_products) == set(PRODUCTS)
    assert result.bom_quantity.requirement_per_product == {
        "ROB-P100": Decimal(6),
        "ROB-P200": Decimal(12),
        "CON-C100": Decimal(4),
        "PAL-P300": Decimal(2),
    }
    assert result.bom_quantity.products_without_requirement == []
    assert all(
        evidence.bom_version_id and evidence.bom_code
        for evidence in result.bom_quantity.evidence
    )


def test_inventory_purchase_production_impact(result):
    """Stored and frozen facts match the accepted metrics."""
    assert result.inventory.available_qty == Decimal(700)
    assert result.purchase.committed_open_qty == Decimal(900)
    assert result.production.current_frozen_demand_qty == Decimal(322)
    assert len(result.production.current_orders) == 9
    assert "MO-2026-000011" not in result.production.remaining_by_order
    assert all(
        line.po_number
        in {"PO-2026-000001", "PO-2026-000004", "PO-2026-000007"}
        for line in result.purchase.lines
    )
    assert all(
        line.timing_classification is PurchaseTimingClass.ARRIVES_BEFORE_LTB
        for line in result.purchase.lines
        if line.remaining_qty > 0
    )


def test_sales_impact_and_material_equivalent(result):
    """Sales exposure and its material equivalent are the accepted values."""
    assert result.sales.current_exposure_orders == 11
    assert result.sales.current_exposure_qty == Decimal(31)
    assert result.sales.potential_exposure_orders == 1
    assert result.sales.potential_exposure_qty == Decimal(1)
    material = result.sales.material_equivalent
    assert isinstance(material.current_material_equivalent_qty, Decimal)
    assert material.current_material_equivalent_qty == Decimal(184)
    assert material.potential_material_equivalent_qty == Decimal(12)
    assert all(
        line.material_equivalent_qty
        == line.remaining_delivery_qty * line.requirement_per_product
        for line in material.lines
    )


def test_alternative_impact(result):
    """B is eligible, C is ineligible, nothing is recommended."""
    by_part = {
        item.alternative_part_number: item.classification
        for item in result.alternatives.assessments
    }
    assert by_part["BRG-6204-B"] is AlternativeClassification.ELIGIBLE
    assert by_part["BRG-6204-C"] is AlternativeClassification.INELIGIBLE
    assert not {"recommended", "best_alternative"} & set(
        result.alternatives.model_dump()
    )


def test_supply_coverage(result):
    """Coverage deltas equal the accepted values."""
    assert result.coverage.inventory_coverage_delta == Decimal(378)
    assert result.coverage.projected_coverage_delta == Decimal(1278)
    assert result.coverage.inventory_covers_current_frozen_demand is True
    assert result.coverage.projected_supply_covers_current_frozen_demand is True


def test_result_is_auditable_and_free_of_scores(result):
    """The result carries evidence and caveats, never a risk score."""
    payload = result.model_dump()
    assert "overall_risk_score" not in payload
    assert "recommended_strategy" not in payload
    assert result.caveats
    assert "neo4j" not in repr(payload)
    assert "sqlalchemy" not in repr(payload)
    assert result.purchase.lines[0].po_number and result.purchase.lines[0].line_number
    assert result.production.current_orders
    assert result.sales.lines[0].order_number and result.sales.lines[0].line_number
