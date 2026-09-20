"""Unit tests for the generated Cypher and value conversion helpers."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.neo4j.repositories.product_structure import (
    _as_datetime,
    _as_decimal,
    effective_bom_condition,
    explosion_query,
    where_used_query,
)


def test_explosion_query_only_walks_the_bom_chain():
    """Every branch uses the explicit BOM chain and no wildcard traversal."""
    query = explosion_query(3)

    assert "[:HAS_BOM]->" in query
    assert "[:HAS_LINE]->" in query
    assert "[:COMPONENT]->" in query
    assert "[*" not in query
    assert query.count("UNION") == 2  # three levels


def test_where_used_query_only_walks_the_bom_chain_upwards():
    """Where-used uses the reverse BOM chain, never a type wildcard."""
    query = where_used_query(2)

    assert "<-[:COMPONENT]-" in query
    assert "<-[:HAS_LINE]-" in query
    assert "<-[:HAS_BOM]-" in query
    assert "[*" not in query
    assert "HAS_REVISION" in query  # only to read the ancestor part type
    assert query.count("RETURN 1 AS bom_level") == 1
    assert query.count("RETURN 2 AS bom_level") == 1


def test_every_level_filters_on_the_same_business_date():
    """Each BOM level carries the effectivity predicate for ``$as_of_date``."""
    levels = 3
    explosion = explosion_query(levels)
    where_used = where_used_query(levels)

    # Every UNION branch repeats the conditions of the levels it walks, and each
    # condition compares both ends of the window against the same parameter.
    expected = 2 * sum(range(1, levels + 1))
    assert explosion.count("$as_of_date") == expected
    assert where_used.count("$as_of_date") == expected
    for level in (1, 2, 3):
        assert f"properties(b{level})['effective_from']" in explosion
        assert f"properties(b{level})['effective_to']" in explosion
        assert f"properties(b{level})['effective_from']" in where_used
        assert f"properties(b{level})['effective_to']" in where_used


def test_effective_condition_treats_missing_property_as_open_ended():
    """A missing ``effective_to`` key means "no end date", not "expired"."""
    condition = effective_bom_condition("b")

    assert "b.status IN $statuses" in condition
    assert "properties(b)['effective_from'] IS NULL" in condition
    assert "properties(b)['effective_to'] IS NULL" in condition
    assert "<= $as_of_date" in condition
    assert ">= $as_of_date" in condition


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.1, Decimal("0.1")), (2.0, Decimal("2.0")), (3, Decimal(3))],
)
def test_decimal_conversion_avoids_binary_float_drift(value, expected):
    """Neo4j floats become the shortest exact decimal representation."""
    assert _as_decimal(value) == expected
    assert str(_as_decimal(value)) == str(expected)


def test_datetime_conversion_handles_none_and_native_values():
    """Temporal conversion never leaks a driver type upward."""
    assert _as_datetime(None) is None
    assert _as_datetime("2026-09-01") is None
