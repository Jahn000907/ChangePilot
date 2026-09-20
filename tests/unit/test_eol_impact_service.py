"""Unit tests for the Supplier EOL impact orchestration (no database)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.domain.dto.impact_metrics import (
    AlternativeClassification,
    PurchaseTimingClass,
)
from app.domain.dto.product_structure import WhereUsedResult
from app.domain.errors import (
    AmbiguousEffectiveBOMError,
    DomainValidationError,
    NoEffectiveBOMError,
    PartRevisionNotFoundError,
)
from app.services.eol_impact import EOLImpactService
from tests.fixtures.eol_impact_fakes import (
    AS_OF,
    EOL_PART,
    REQUIREMENT_PER_PRODUCT,
    REVISION,
    FakeERPFactService,
    FakeProductStructureService,
    alternative_result,
    explosion_result,
    inventory_facts,
    production_facts,
    purchase_facts,
    sales_facts,
    supplier_facts,
    where_used_result,
)

PRODUCTS = ("ROB-P100", "ROB-P200", "CON-C100", "PAL-P300")


def build_service(
    *, product_structure: FakeProductStructureService | None = None, **erp_kwargs
) -> tuple[EOLImpactService, FakeProductStructureService, FakeERPFactService]:
    """Return the orchestration service wired with fakes."""
    structure = product_structure or FakeProductStructureService(
        where_used_result=where_used_result(),
        explosion_results={
            product: explosion_result(product) for product in PRODUCTS
        },
        alternatives=alternative_result(),
    )
    erp = FakeERPFactService(
        suppliers=erp_kwargs.pop("suppliers", supplier_facts()),
        inventory_facts=erp_kwargs.pop("inventory_facts", inventory_facts()),
        purchase_facts=erp_kwargs.pop("purchase_facts", purchase_facts()),
        production_facts=erp_kwargs.pop("production_facts", production_facts()),
        sales_facts=erp_kwargs.pop("sales_facts", sales_facts()),
        **erp_kwargs,
    )
    return EOLImpactService(product_structure=structure, erp_facts=erp), structure, erp


def analyze(service: EOLImpactService):
    """Run the analysis as the caller would."""
    return service.analyze_supplier_eol(EOL_PART, REVISION, AS_OF)


def test_orchestration_reuses_the_existing_services():
    """Every fact and every graph answer comes from the 2A / 2B services."""
    service, structure, erp = build_service()

    analyze(service)

    assert structure.where_used_calls == [(EOL_PART, REVISION, 5, AS_OF)]
    assert structure.alternative_calls == [(EOL_PART, REVISION)]
    # Affected products are processed in the deterministic (sorted) order of the
    # where-used result.
    assert sorted(call[0] for call in structure.explosion_calls) == sorted(PRODUCTS)
    assert [call[0] for call in structure.explosion_calls] == sorted(PRODUCTS)
    assert all(call[3] == AS_OF for call in structure.explosion_calls)
    assert [call[0] for call in erp.calls] == [
        "supplier_parts",
        "inventory",
        "purchase_order_lines",
        "production_requirements",
        "sales_order_lines",
    ]
    sales_call = next(call for call in erp.calls if call[0] == "sales_order_lines")
    assert sales_call[1] == tuple(
        (product, REVISION) for product in sorted(PRODUCTS)
    )


def test_product_impact_lists_assemblies_and_products():
    """The where-used evidence becomes the product impact structure."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    assert set(result.product.affected_finished_products) == set(PRODUCTS)
    assert set(result.product.direct_parent_assemblies) == {
        "ASM-GEARBOX100",
        "ASM-GEARBOX200",
        "ASM-GEARBOX300",
        "ASM-GEARBOX400",
    }
    assert "ASM-ARM100" in result.product.affected_assemblies
    assert result.product.as_of_date == AS_OF
    rob_path = next(
        path
        for path in result.product.paths
        if path.ancestor_part_number == "ROB-P100"
    )
    assert rob_path.path[0] == EOL_PART
    assert rob_path.bom_code == "BOM-ROB-P100-01"
    assert rob_path.bom_level == 4


def test_bom_quantity_impact_uses_explosion_totals():
    """Per-product requirements come from the explosion ``totals``."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    assert result.bom_quantity.requirement_per_product == REQUIREMENT_PER_PRODUCT
    assert all(
        isinstance(quantity, Decimal)
        for quantity in result.bom_quantity.requirement_per_product.values()
    )
    assert result.bom_quantity.products_without_requirement == []
    assert {
        evidence.product_part_number for evidence in result.bom_quantity.evidence
    } == set(PRODUCTS)


def test_inventory_purchase_and_production_metrics():
    """The 2C metrics of the golden facts appear unchanged in the result."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    assert result.inventory.total_on_hand == Decimal(820)
    assert result.inventory.total_reserved == Decimal(120)
    assert result.inventory.available_qty == Decimal(700)
    assert result.purchase.committed_open_qty == Decimal(900)
    assert result.purchase.potential_qty == Decimal(0)
    assert result.production.current_frozen_demand_qty == Decimal(322)
    assert result.production.current_orders == sorted(
        {
            "MO-2026-000001",
            "MO-2026-000002",
            "MO-2026-000004",
            "MO-2026-000005",
            "MO-2026-000006",
            "MO-2026-000007",
            "MO-2026-000008",
            "MO-2026-000009",
            "MO-2026-000010",
        }
    )
    assert result.production.historical_orders == ["MO-2026-000003"]
    assert sum(result.production.remaining_by_product.values()) == Decimal(322)


def test_purchase_timing_classification_of_the_golden_orders():
    """All three planned deliveries fall before the last-time-buy date."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    assert all(
        line.timing_classification is PurchaseTimingClass.ARRIVES_BEFORE_LTB
        for line in result.purchase.lines
    )
    assert result.purchase.timing_counts["ARRIVES_BEFORE_LTB"] == 3
    assert result.purchase.reference_eol_date == date(2027, 1, 31)


def test_sales_exposure_and_material_equivalent():
    """Sales exposure and its material equivalent are computed separately."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    assert result.sales.current_exposure_orders == 11
    assert result.sales.current_exposure_qty == Decimal(31)
    assert result.sales.potential_exposure_orders == 1
    assert result.sales.potential_exposure_qty == Decimal(1)
    assert result.sales.not_exposed_orders == 3
    assert isinstance(
        result.sales.material_equivalent.current_material_equivalent_qty, Decimal
    )
    assert result.sales.material_equivalent.current_material_equivalent_qty == Decimal(
        184
    )
    assert result.sales.material_equivalent.potential_material_equivalent_qty == (
        Decimal(12)
    )
    assert all(
        line.material_equivalent_qty
        == line.remaining_delivery_qty * line.requirement_per_product
        for line in result.sales.material_equivalent.lines
    )


def test_material_equivalent_is_never_added_to_production_demand():
    """The result keeps the two exposures apart and says so explicitly."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    fields = set(result.model_dump())
    assert not fields & {"total_demand", "combined_demand", "overall_risk"}
    assert not {"total_demand", "combined_demand"} & set(
        result.sales.model_dump()
    )
    assert any("不得与 production" in caveat for caveat in result.caveats)
    # The two numbers are independent facts, not a computed total.
    assert (
        result.sales.material_equivalent.current_material_equivalent_qty
        != result.production.current_frozen_demand_qty
    )


def test_alternative_impact_classifies_without_recommending():
    """Alternatives are classified only."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    by_part = {
        item.alternative_part_number: item.classification
        for item in result.alternatives.assessments
    }
    assert by_part == {
        "BRG-6204-B": AlternativeClassification.ELIGIBLE,
        "BRG-6204-C": AlternativeClassification.INELIGIBLE,
    }
    assert (result.alternatives.eligible_count, result.alternatives.ineligible_count) == (
        1,
        1,
    )
    assert not {"recommended", "best_alternative", "selected"} & set(
        result.alternatives.model_dump()
    )


def test_supply_coverage_matches_the_golden_numbers():
    """Coverage deltas follow the agreed formulas."""
    service, _structure, _erp = build_service()

    result = analyze(service)

    assert result.coverage.inventory_coverage_delta == Decimal(378)
    assert result.coverage.projected_coverage_delta == Decimal(1278)
    assert result.coverage.inventory_covers_current_frozen_demand is True
    assert result.coverage.projected_supply_covers_current_frozen_demand is True
    assert result.coverage.committed_open_purchase_qty == Decimal(900)


def test_multiple_supplier_relationships_are_all_kept():
    """No supplier is dropped or ranked."""
    extra = supplier_facts()[0].model_copy(
        update={
            "supplier_code": "SUP-002",
            "supplier_name": "GearTech",
            "supplier_part_status": "ACTIVE",
            "eol_date": date(2027, 6, 30),
        }
    )
    service, _structure, _erp = build_service(
        suppliers=[*supplier_facts(), extra]
    )

    result = analyze(service)

    assert [item.supplier_code for item in result.supplier.suppliers] == [
        "SUP-001",
        "SUP-002",
    ]
    # The earliest EOL window drives the date classification.
    assert result.supplier.reference_supplier_code == "SUP-001"
    assert result.supplier.reference_eol_date == date(2027, 1, 31)


def test_missing_business_facts_yield_zero_results():
    """Empty facts are zero / empty results, never an exception."""
    empty_where_used = WhereUsedResult(
        part_number=EOL_PART,
        revision_code=REVISION,
        as_of_date=AS_OF,
        bom_statuses=("RELEASED",),
        max_depth=5,
        rows=[],
        ancestors=[],
        products=[],
    )
    structure = FakeProductStructureService(
        where_used_result=empty_where_used,
        explosion_results={},
        alternatives=None,
    )
    service, _structure, erp = build_service(
        product_structure=structure,
        suppliers=[],
        inventory_facts=[],
        purchase_facts=[],
        production_facts=[],
        sales_facts=[],
    )

    result = analyze(service)

    assert result.supplier.suppliers == []
    assert result.supplier.reference_supplier_code is None
    assert result.product.affected_finished_products == []
    assert result.inventory.available_qty == Decimal(0)
    assert result.purchase.committed_open_qty == Decimal(0)
    assert result.production.current_frozen_demand_qty == Decimal(0)
    assert result.sales.current_exposure_orders == 0
    assert result.sales.material_equivalent.current_material_equivalent_qty == Decimal(0)
    assert result.coverage.inventory_coverage_delta == Decimal(0)
    assert result.coverage.inventory_covers_current_frozen_demand is True
    # Without affected products the sales query is skipped entirely.
    assert not [call for call in erp.calls if call[0] == "sales_order_lines"]


def test_purchase_timing_is_none_without_an_eol_window():
    """Without any EOL window nothing can be classified."""
    service, _structure, _erp = build_service(
        suppliers=[
            supplier_facts()[0].model_copy(
                update={
                    "supplier_part_status": "ACTIVE",
                    "last_time_buy_date": None,
                    "eol_date": None,
                }
            )
        ]
    )

    result = analyze(service)

    assert result.supplier.reference_eol_date is None
    assert all(
        line.timing_classification is None for line in result.purchase.lines
    )


def test_expected_date_unknown_is_reported_when_the_window_exists():
    """A line without a planned date is classified as unknown."""
    service, _structure, _erp = build_service(
        purchase_facts=[
            purchase_facts()[0].model_copy(update={"expected_date": None})
        ]
    )

    result = analyze(service)

    assert (
        result.purchase.lines[0].timing_classification
        is PurchaseTimingClass.EXPECTED_DATE_UNKNOWN
    )


@pytest.mark.parametrize(
    "error",
    [
        PartRevisionNotFoundError("missing"),
        NoEffectiveBOMError("no effective BOM"),
        AmbiguousEffectiveBOMError("two effective BOMs"),
    ],
)
def test_domain_errors_propagate_unchanged(error):
    """Genuine data problems are not masked by the orchestration."""
    structure = FakeProductStructureService(
        where_used_result=where_used_result(), error=error
    )
    service, _structure, _erp = build_service(product_structure=structure)

    with pytest.raises(type(error)):
        analyze(service)


def test_analysis_requires_a_valid_business_date():
    """The business date is mandatory and must be a date."""
    service, _structure, _erp = build_service()

    with pytest.raises(DomainValidationError):
        service.analyze_supplier_eol(EOL_PART, REVISION, datetime(2026, 9, 20, 8, tzinfo=UTC))
    with pytest.raises(TypeError):
        service.analyze_supplier_eol(EOL_PART, REVISION)  # type: ignore[call-arg]
    with pytest.raises(DomainValidationError):
        service.analyze_supplier_eol("  ", REVISION, AS_OF)
