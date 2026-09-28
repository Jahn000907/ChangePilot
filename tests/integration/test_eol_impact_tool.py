"""Minimal integration test for the Supplier EOL application tool."""

from __future__ import annotations

import json
from datetime import date

import pytest
from neo4j.exceptions import Neo4jError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.neo4j.driver import close_driver, get_driver
from app.db.postgres.session import create_session
from app.domain.errors import EntityNotFoundError
from app.tools import (
    SupplierEOLImpactInput,
    SupplierEOLImpactResult,
    analyze_supplier_eol,
)


def test_supplier_eol_tool_runs_golden_seed_and_serializes():
    """The first tool returns a JSON-serializable domain result."""
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

    request = SupplierEOLImpactInput(
        part_number="BRG-6204-A",
        revision_code="A",
        as_of_date=date(2026, 9, 20),
    )
    try:
        result = analyze_supplier_eol(request)
    except EntityNotFoundError as exc:  # pragma: no cover - seed dependent
        pytest.skip(f"golden seed is not loaded: {exc}")
    finally:
        close_driver()

    assert isinstance(result, SupplierEOLImpactResult)
    payload = json.loads(result.model_dump_json())
    assert payload["part_number"] == "BRG-6204-A"
    assert payload["revision_code"] == "A"
    assert sorted(payload["product"]["affected_finished_products"]) == [
        "CON-C100",
        "PAL-P300",
        "ROB-P100",
        "ROB-P200",
    ]
