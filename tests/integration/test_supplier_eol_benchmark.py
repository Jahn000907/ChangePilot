"""Acceptance tests for the deterministic CASE-EOL-001 benchmark."""

from __future__ import annotations

import json

import pytest
from neo4j.exceptions import Neo4jError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.neo4j.driver import close_driver, get_driver
from app.db.postgres.models.ecm import ChangeCase
from app.db.postgres.session import create_session
from evals.evaluators import evaluate_impact_recall
from evals.run_supplier_eol import load_benchmark_case, run_supplier_eol_benchmark


def _require_backends() -> None:
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


def _benchmark_case_count() -> int:
    with create_session() as session:
        return session.scalar(
            select(func.count())
            .select_from(ChangeCase)
            .where(ChangeCase.case_number.like("CASE-EVAL-%"))
        ) or 0


def test_benchmark_case_loads_and_bad_recall_loses_score():
    """The checked-in contract loads and an intentionally incomplete result fails."""
    benchmark = load_benchmark_case()
    assert benchmark.scenario_id == "CASE-EOL-001"
    assert benchmark.expected.affected_finished_products

    metric = evaluate_impact_recall(
        ["ROB-P100"],
        benchmark.expected.affected_finished_products,
    )
    assert metric.passed is False
    assert 0.0 < metric.score < 1.0
    assert metric.issues


def test_fake_benchmark_runs_scores_serializes_and_cleans_up():
    """The reproducible APPROVE path earns all metrics and leaves no test case."""
    _require_backends()
    count_before = _benchmark_case_count()
    try:
        result = run_supplier_eol_benchmark()
    finally:
        close_driver()

    assert result.scenario_id == "CASE-EOL-001"
    assert set(result.metrics) == {
        "impact_recall",
        "numerical_correctness",
        "alternative_correctness",
        "strategy_grounding",
        "review_safety",
        "human_approval_safety",
        "execution_correctness",
    }
    assert all(metric.passed for metric in result.metrics.values())
    assert result.passed is True
    assert result.score == 1.0
    assert json.loads(result.model_dump_json())["score"] == 1.0
    assert _benchmark_case_count() == count_before
