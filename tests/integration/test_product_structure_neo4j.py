"""Integration tests against the real Neo4j database with the golden seed.

These tests need the Docker Neo4j instance and the loaded golden seed. When the
database is unreachable, or the seed is missing, they skip with a clear reason
instead of failing: the same checks run deterministically in
``scripts/check_data_consistency.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from neo4j.exceptions import Neo4jError

from app.db.neo4j.driver import close_driver, get_driver
from app.domain.errors import NoEffectiveBOMError, PartRevisionNotFoundError
from app.services.product_structure import (
    ProductStructureService,
    default_business_date,
)

EOL_PART = "BRG-6204-A"
PRODUCTS = ("ROB-P100", "ROB-P200", "CON-C100", "PAL-P300")

#: Business date used by the golden seed checks. The seed releases its BOM
#: versions with ``effective_from = 2026-01-01`` and no end date.
SEED_AS_OF = date(2026, 9, 20)

#: A date before the seeded BOM becomes effective.
BEFORE_SEED_EFFECTIVITY = date(2025, 12, 31)


@pytest.fixture(scope="module")
def service() -> ProductStructureService:
    """Return a service bound to the shared driver, skipping without Neo4j."""
    try:
        get_driver().verify_connectivity()
    except (Neo4jError, OSError) as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Neo4j is not reachable: {exc}")
    product_service = ProductStructureService()
    try:
        product_service.get_part_revision("ROB-P100", "A")
    except PartRevisionNotFoundError:  # pragma: no cover - environment dependent
        pytest.skip("golden seed is not loaded (ROB-P100 missing)")
    yield product_service
    close_driver()


def test_explosion_of_rob_p100_contains_the_eol_bearing(service):
    """ROB-P100 explodes through four levels down to BRG-6204-A."""
    result = service.explode_bom("ROB-P100", "A", as_of_date=SEED_AS_OF)

    assert result.max_depth == 5
    assert result.bom_statuses == ("RELEASED",)
    assert result.as_of_date == SEED_AS_OF
    assert result.bom_code == "BOM-ROB-P100-01"
    assert result.bom_version_id
    levels = {row.bom_level for row in result.rows}
    assert levels == {1, 2, 3, 4}
    assert EOL_PART in result.component_part_numbers

    bearing_rows = [row for row in result.rows if row.component_part_number == EOL_PART]
    assert len(bearing_rows) == 1
    bearing = bearing_rows[0]
    assert bearing.bom_level == 4
    assert bearing.parent_part_number == "ASM-GEARBOX100"
    assert bearing.quantity_per == Decimal(2)
    assert bearing.cumulative_quantity == Decimal(6)  # 1 x 3 x 1 x 2
    assert result.quantity_of(EOL_PART) == Decimal(6)
    assert isinstance(bearing.cumulative_quantity, Decimal)


def test_where_used_of_the_eol_bearing_reaches_four_products(service):
    """BRG-6204-A is used by two or more gearboxes and all four products."""
    result = service.where_used(EOL_PART, "A", as_of_date=SEED_AS_OF)

    assert result.as_of_date == SEED_AS_OF
    assert set(PRODUCTS) <= set(result.products)
    gearboxes = {
        row.ancestor_part_number
        for row in result.rows
        if row.ancestor_part_number.startswith("ASM-GEARBOX")
    }
    assert len(gearboxes) >= 2
    rob_path = [row for row in result.rows if row.ancestor_part_number == "ROB-P100"]
    assert rob_path, "ROB-P100 must appear in the where-used result"
    assert rob_path[0].bom_level == 4
    assert rob_path[0].path[0] == EOL_PART
    assert rob_path[0].path[-1] == "ROB-P100"
    assert rob_path[0].bom_code == "BOM-ROB-P100-01"


def test_default_business_date_is_today(service):
    """Without ``as_of_date`` the service evaluates effectivity as of today."""
    result = service.explode_bom("ROB-P100", "A")

    assert result.as_of_date == default_business_date()
    assert result.quantity_of(EOL_PART) == Decimal(6)


def test_bom_is_not_effective_before_its_start_date(service):
    """Before ``effective_from`` the released BOM is not usable."""
    with pytest.raises(NoEffectiveBOMError) as excinfo:
        service.explode_bom("ROB-P100", "A", as_of_date=BEFORE_SEED_EFFECTIVITY)

    message = str(excinfo.value)
    assert "ROB-P100" in message
    assert BEFORE_SEED_EFFECTIVITY.isoformat() in message


def test_where_used_ignores_bom_that_is_not_effective(service):
    """A stored BOM that is not effective on the date yields no usage."""
    result = service.where_used(EOL_PART, "A", as_of_date=BEFORE_SEED_EFFECTIVITY)

    assert result.as_of_date == BEFORE_SEED_EFFECTIVITY
    assert result.rows == []
    assert result.ancestors == []
    assert result.products == []


def test_alternatives_of_the_eol_bearing(service):
    """The qualified and unqualified candidates are returned as facts."""
    result = service.find_alternatives(EOL_PART, "A")

    by_part = {row.alternative_part_number: row for row in result.rows}
    assert by_part["BRG-6204-B"].qualification_status == "QUALIFIED"
    assert by_part["BRG-6204-B"].replacement_type == "DIRECT"
    assert by_part["BRG-6204-C"].qualification_status == "UNQUALIFIED"
    assert all(row.alternative_revision_code == "A" for row in result.rows)


def test_part_revision_and_missing_revision(service):
    """A known revision is returned; an unknown one raises a domain error."""
    revision = service.get_part_revision(EOL_PART, "A")
    assert revision.part_type == "PURCHASED_PART"
    assert revision.lifecycle_state == "RELEASED"

    with pytest.raises(PartRevisionNotFoundError):
        service.get_part_revision("BRG-6204-A", "Z")
