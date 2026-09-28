"""Golden Seed smoke tests for the first group of Agent read tools."""

from __future__ import annotations

import json
from datetime import date

import pytest
from neo4j.exceptions import Neo4jError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.neo4j.driver import close_driver, get_driver
from app.db.postgres.session import create_session
from app.tools import (
    FindWhereUsedInput,
    GetAlternativesInput,
    GetBOMStructureInput,
    GetInventoryInput,
    GetPurchaseOrdersInput,
    find_where_used,
    get_alternatives,
    get_bom_structure,
    get_inventory,
    get_purchase_orders,
)

AS_OF_DATE = date(2026, 9, 20)


@pytest.fixture(scope="module", autouse=True)
def golden_databases():
    """Require the existing read-only Golden Seed databases."""
    try:
        get_driver().verify_connectivity()
    except (Neo4jError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"Neo4j is not reachable: {exc}")
    try:
        with create_session() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:  # pragma: no cover - environment
        close_driver()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    yield
    close_driver()


def test_product_structure_tools_run_and_serialize():
    """BOM, where-used and alternative facts use stable serialized DTOs."""
    bom = get_bom_structure(
        GetBOMStructureInput(
            part_number="ROB-P100",
            revision_code="A",
            as_of_date=AS_OF_DATE,
        )
    )
    where_used = find_where_used(
        FindWhereUsedInput(
            part_number="BRG-6204-A",
            revision_code="A",
            as_of_date=AS_OF_DATE,
        )
    )
    alternatives = get_alternatives(
        GetAlternativesInput(part_number="BRG-6204-A", revision_code="A")
    )

    bom_payload = json.loads(bom.model_dump_json())
    where_used_payload = json.loads(where_used.model_dump_json())
    alternatives_payload = json.loads(alternatives.model_dump_json())

    assert bom_payload["rows"]
    assert "BRG-6204-A" in bom.component_part_numbers
    assert sorted(where_used_payload["products"]) == [
        "CON-C100",
        "PAL-P300",
        "ROB-P100",
        "ROB-P200",
    ]
    assert {
        row["alternative_part_number"] for row in alternatives_payload["rows"]
    } == {"BRG-6204-B", "BRG-6204-C"}


def test_erp_fact_tools_run_and_serialize():
    """Inventory and purchase-order tools return serialized Golden facts."""
    inventory = get_inventory(
        GetInventoryInput(part_number="BRG-6204-A", revision_code="A")
    )
    purchase_orders = get_purchase_orders(
        GetPurchaseOrdersInput(part_number="BRG-6204-A", revision_code="A")
    )

    inventory_payload = json.loads(inventory.model_dump_json())
    purchase_payload = json.loads(purchase_orders.model_dump_json())

    assert inventory_payload["rows"]
    assert inventory_payload["rows"][0]["part_number"] == "BRG-6204-A"
    assert purchase_payload["rows"]
    assert all(row["part_number"] == "BRG-6204-A" for row in purchase_payload["rows"])
