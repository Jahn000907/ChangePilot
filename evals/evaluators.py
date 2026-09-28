"""Deterministic evaluators for the single Supplier EOL benchmark."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.dto.eol_impact import SupplierEOLImpactResult
from app.domain.dto.strategy import StrategyCandidate
from app.workflows.state import SupplierEOLWorkflowState
from evals.models import EvaluationMetric, StepEvidence, SupplierEOLExpectedResult


def evaluate_impact_recall(
    actual_products: Sequence[str],
    expected_products: Sequence[str],
) -> EvaluationMetric:
    """Measure recall of the accepted affected finished-product set."""
    expected = set(expected_products)
    matched = expected.intersection(actual_products)
    recall = len(matched) / len(expected) if expected else 1.0
    missing = sorted(expected - matched)
    return EvaluationMetric(
        name="impact_recall",
        passed=not missing,
        score=recall,
        details={
            "expected_count": len(expected),
            "matched_count": len(matched),
            "recall": recall,
            "missing_products": missing,
        },
        issues=[f"Missing affected product: {part}" for part in missing],
    )


def evaluate_numerical_correctness(
    impact: SupplierEOLImpactResult | None,
    expected: SupplierEOLExpectedResult,
) -> EvaluationMetric:
    """Compare only stable numerical facts already asserted by Golden tests."""
    if impact is None:
        return _missing_metric("numerical_correctness", "Impact result is missing")
    checks = {
        "inventory_available_qty": impact.inventory.available_qty
        == expected.inventory_available_qty,
        "purchase_committed_open_qty": impact.purchase.committed_open_qty
        == expected.purchase_committed_open_qty,
        "purchase_order_count": len(impact.purchase.orders)
        == expected.purchase_order_count,
        "production_frozen_demand_qty": impact.production.current_frozen_demand_qty
        == expected.production_frozen_demand_qty,
        "production_order_count": len(impact.production.current_orders)
        == expected.production_order_count,
        "purchase_impact_present": not expected.expects_purchase_impact
        or bool(impact.purchase.orders),
        "production_impact_present": not expected.expects_production_impact
        or bool(impact.production.current_orders),
    }
    issues = [f"Golden numerical fact mismatch: {name}" for name, ok in checks.items() if not ok]
    return _checks_metric("numerical_correctness", checks, issues)


def evaluate_alternative_correctness(
    impact: SupplierEOLImpactResult | None,
    expected: SupplierEOLExpectedResult,
) -> EvaluationMetric:
    """Verify the qualified and unqualified Golden alternatives."""
    if impact is None:
        return _missing_metric("alternative_correctness", "Impact result is missing")
    actual = {
        item.alternative_part_number: item.qualification_status
        for item in impact.alternatives.assessments
    }
    checks = {
        part_number: actual.get(part_number) == qualification
        for part_number, qualification in expected.alternatives.items()
    }
    issues = [
        f"Alternative {part_number} expected {expected.alternatives[part_number]}, "
        f"got {actual.get(part_number)!r}"
        for part_number, ok in checks.items()
        if not ok
    ]
    return _checks_metric(
        "alternative_correctness",
        checks,
        issues,
        details={"actual": actual, "expected": expected.alternatives},
    )


def evaluate_strategy_grounding(
    strategies: Sequence[StrategyCandidate],
    expected: SupplierEOLExpectedResult,
) -> EvaluationMetric:
    """Reject empty reasoning/actions and direct-switch claims for unqualified parts."""
    issues: list[str] = []
    unqualified = {
        part for part, status in expected.alternatives.items() if status == "UNQUALIFIED"
    }
    direct_switch_phrases = (
        "direct switch",
        "immediate switch",
        "direct replacement",
        "直接切换",
        "直接替换",
    )
    if not strategies:
        issues.append("No strategy candidate was generated")
    for index, strategy in enumerate(strategies):
        if not strategy.rationale.strip():
            issues.append(f"Strategy {index} has no rationale")
        if not strategy.actions:
            issues.append(f"Strategy {index} has no action")
        text = " ".join(
            [strategy.title, strategy.summary, strategy.rationale, *strategy.actions]
        ).lower()
        for part_number in unqualified:
            if part_number.lower() in text and any(
                phrase in text for phrase in direct_switch_phrases
            ):
                issues.append(
                    f"Strategy {index} describes unqualified {part_number} as directly usable"
                )
    return EvaluationMetric(
        name="strategy_grounding",
        passed=not issues,
        score=1.0 if not issues else 0.0,
        details={"strategy_count": len(strategies)},
        issues=issues,
    )


def evaluate_review_safety(
    state: SupplierEOLWorkflowState,
    steps: Sequence[StepEvidence],
    *,
    max_revisions: int,
) -> EvaluationMetric:
    """Verify legal review output and a bounded, evidenced revision loop."""
    review_steps = sum(step.node_name == "review" for step in steps)
    strategy_steps = sum(step.node_name == "strategy_generation" for step in steps)
    decision = state.review_result.decision.value if state.review_result else None
    checks = {
        "review_executed": review_steps >= 1,
        "valid_decision": decision in {"PASS", "REVISE"},
        "revision_bound": state.revision_count <= max_revisions,
        "revision_regenerated": state.revision_count == 0
        or strategy_steps >= state.revision_count + 1,
    }
    issues = [f"Review safety check failed: {name}" for name, ok in checks.items() if not ok]
    return _checks_metric(
        "review_safety",
        checks,
        issues,
        details={
            "decision": decision,
            "revision_count": state.revision_count,
            "review_steps": review_steps,
            "strategy_steps": strategy_steps,
        },
    )


def evaluate_human_approval_safety(
    state: SupplierEOLWorkflowState,
    steps: Sequence[StepEvidence],
    *,
    was_interrupted: bool,
) -> EvaluationMetric:
    """Ensure only an approved, previously interrupted run reaches execution."""
    decision = state.approval.decision.value if state.approval else None
    waiting_step = any(
        step.node_name == "human_approval" and step.status == "WAITING_HUMAN"
        for step in steps
    )
    execution_present = state.execution_result is not None
    checks = {
        "approval_interrupt": was_interrupted and waiting_step,
        "approval_recorded": decision in {"APPROVE", "REJECT"},
        "approve_allows_execution": decision != "APPROVE" or execution_present,
        "reject_blocks_execution": decision != "REJECT" or not execution_present,
    }
    issues = [
        f"Human approval safety check failed: {name}" for name, ok in checks.items() if not ok
    ]
    return _checks_metric("human_approval_safety", checks, issues)


def evaluate_execution_correctness(
    state: SupplierEOLWorkflowState,
) -> EvaluationMetric:
    """Check execution identifiers for APPROVE and absence for REJECT."""
    decision = state.approval.decision.value if state.approval else None
    execution = state.execution_result
    if decision == "REJECT":
        checks = {"reject_has_no_execution": execution is None}
    else:
        checks = {
            "strategy_selected": execution is not None and execution.strategy_id is not None,
            "eco_created": execution is not None and execution.eco_id is not None,
            "execution_job_created": execution is not None
            and bool(execution.execution_job_ids),
        }
    issues = [
        f"Execution correctness check failed: {name}" for name, ok in checks.items() if not ok
    ]
    return _checks_metric("execution_correctness", checks, issues)


def _checks_metric(
    name: str,
    checks: dict[str, bool],
    issues: list[str],
    *,
    details: dict[str, object] | None = None,
) -> EvaluationMetric:
    score = sum(checks.values()) / len(checks) if checks else 1.0
    metric_details = dict(details or {})
    metric_details["checks"] = checks
    return EvaluationMetric(
        name=name,
        passed=all(checks.values()),
        score=score,
        details=metric_details,
        issues=issues,
    )


def _missing_metric(name: str, issue: str) -> EvaluationMetric:
    return EvaluationMetric(name=name, passed=False, score=0.0, issues=[issue])
