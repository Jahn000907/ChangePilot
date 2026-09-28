"""Reproducible runner for the CASE-EOL-001 Supplier EOL benchmark."""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select

from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.db.neo4j.driver import close_driver
from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.models.audit import AuditEvent
from app.db.postgres.models.ecm import (
    ChangeCase,
    ChangeImpact,
    ChangeStrategy,
    ChangeStrategyAction,
    EngineeringChangeOrder,
    EngineeringChangeRequest,
    ExecutionJob,
)
from app.db.postgres.session import create_session
from app.domain.dto.approval import HumanApproval
from app.domain.dto.change_case import SupplierEOLChangeCaseInput
from app.workflows.state import SupplierEOLWorkflowState
from app.workflows.supplier_eol import (
    MAX_STRATEGY_REVISIONS,
    resume_supplier_eol_workflow,
    run_supplier_eol_workflow,
)
from evals.evaluators import (
    evaluate_alternative_correctness,
    evaluate_execution_correctness,
    evaluate_human_approval_safety,
    evaluate_impact_recall,
    evaluate_numerical_correctness,
    evaluate_review_safety,
    evaluate_strategy_grounding,
)
from evals.models import (
    EvaluationMetric,
    EvaluationResult,
    StepEvidence,
    SupplierEOLBenchmarkCase,
)

BENCHMARK_PATH = Path(__file__).parent / "benchmarks" / "case_eol_001.json"


class _ScenarioEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_type: str
    supplier_code: str
    supplier: str
    part_number: str
    revision_code: str
    last_time_buy_date: date
    eol_date: date


class _FakeStrategyLLM:
    """Return one fact-grounded, deterministic strategy."""

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return json.dumps(
            {
                "strategies": [
                    {
                        "strategy_type": "QUALIFIED_ALTERNATIVE",
                        "title": "Validate the qualified replacement",
                        "summary": "Evaluate BRG-6204-B under controlled change governance.",
                        "rationale": (
                            "Impact facts classify BRG-6204-B as qualified while "
                            "BRG-6204-C remains unqualified."
                        ),
                        "actions": [
                            "Confirm BRG-6204-B applicability for each affected product",
                            "Retain engineering approval before release",
                        ],
                        "risks": ["Product-specific validation may still be required"],
                    }
                ]
            }
        )


class _FakeReviewLLM:
    """Verify alternatives through one real read-only Tool, then PASS."""

    def __init__(self) -> None:
        self._calls = 0

    def invoke_with_tools(
        self,
        *,
        messages: Sequence[BaseMessage],
        tools: Sequence[BaseTool],
    ) -> AIMessage:
        self._calls += 1
        if self._calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_alternatives",
                        "args": {
                            "part_number": "BRG-6204-A",
                            "revision_code": "A",
                        },
                        "id": "benchmark-alternatives",
                        "type": "tool_call",
                    }
                ],
            )
        if not tools or not isinstance(messages[-1], ToolMessage):
            raise ValueError("Fake review expected a ToolMessage before its decision")
        return AIMessage(
            content=json.dumps(
                {
                    "decision": "PASS",
                    "summary": "Strategy is consistent with the verified impact facts.",
                    "issues": [],
                    "recommendations": ["Keep release subject to human approval."],
                }
            )
        )


def load_benchmark_case(path: Path = BENCHMARK_PATH) -> SupplierEOLBenchmarkCase:
    """Load and validate the checked-in CASE-EOL-001 benchmark contract."""
    return SupplierEOLBenchmarkCase.model_validate_json(path.read_text(encoding="utf-8"))


def run_supplier_eol_benchmark(
    *,
    llm_mode: Literal["fake", "deepseek"] = "fake",
    cleanup: bool = True,
) -> EvaluationResult:
    """Run, approve, score and optionally clean one Golden workflow execution."""
    benchmark = load_benchmark_case()
    scenario_path = (BENCHMARK_PATH.parent / benchmark.scenario_file).resolve()
    scenario = _ScenarioEvent.model_validate_json(scenario_path.read_text(encoding="utf-8"))
    suffix = uuid.uuid4().hex[:12]
    request = SupplierEOLChangeCaseInput(
        case_number=f"CASE-EVAL-{suffix}",
        ecr_number=f"ECR-EVAL-{suffix}",
        idempotency_key=f"eval:{benchmark.scenario_id}:{suffix}",
        supplier_code=scenario.supplier_code,
        supplier_name=scenario.supplier,
        part_number=scenario.part_number,
        revision_code=scenario.revision_code,
        last_time_buy_date=scenario.last_time_buy_date,
        eol_date=scenario.eol_date,
        as_of_date=benchmark.as_of_date,
        requested_by="supplier-eol-benchmark",
        created_by="supplier-eol-benchmark",
        source_type=scenario.source_type,
    )
    checkpointer = InMemorySaver()
    state: SupplierEOLWorkflowState | None = None
    try:
        strategy_agent = (
            StrategyAgent(_FakeStrategyLLM()) if llm_mode == "fake" else None
        )
        review_agent = ReviewAgent(_FakeReviewLLM()) if llm_mode == "fake" else None
        interrupted = run_supplier_eol_workflow(
            request,
            thread_id=f"benchmark-{suffix}",
            strategy_agent=strategy_agent,
            review_agent=review_agent,
            checkpointer=checkpointer,
        )
        state = interrupted.state
        was_interrupted = interrupted.status == "INTERRUPTED"
        completed = resume_supplier_eol_workflow(
            thread_id=interrupted.thread_id,
            approval=HumanApproval(
                decision="APPROVE",
                comment="Deterministic benchmark approval",
                reviewer="benchmark-runner",
            ),
            checkpointer=checkpointer,
        )
        state = completed.state
        steps = _load_step_evidence(state)
        metrics = _evaluate(benchmark, state, steps, was_interrupted=was_interrupted)
        score = sum(metric.score for metric in metrics.values()) / len(metrics)
        issues = [issue for metric in metrics.values() for issue in metric.issues]
        return EvaluationResult(
            scenario_id=benchmark.scenario_id,
            passed=all(metric.passed for metric in metrics.values()),
            score=score,
            metrics=metrics,
            issues=issues,
        )
    finally:
        close_driver()
        if cleanup and state is not None:
            _cleanup_run(state)


def _evaluate(
    benchmark: SupplierEOLBenchmarkCase,
    state: SupplierEOLWorkflowState,
    steps: Sequence[StepEvidence],
    *,
    was_interrupted: bool,
) -> dict[str, EvaluationMetric]:
    expected = benchmark.expected
    actual_products = state.impact.affected_product_numbers if state.impact else []
    metrics = [
        evaluate_impact_recall(actual_products, expected.affected_finished_products),
        evaluate_numerical_correctness(state.impact, expected),
        evaluate_alternative_correctness(state.impact, expected),
        evaluate_strategy_grounding(state.strategies, expected),
        evaluate_review_safety(state, steps, max_revisions=MAX_STRATEGY_REVISIONS),
        evaluate_human_approval_safety(
            state,
            steps,
            was_interrupted=was_interrupted,
        ),
        evaluate_execution_correctness(state),
    ]
    return {metric.name: metric for metric in metrics}


def _load_step_evidence(state: SupplierEOLWorkflowState) -> list[StepEvidence]:
    if state.run_id is None:
        return []
    with create_session() as session:
        rows = session.execute(
            select(AgentStep.node_name, AgentStep.status).where(
                AgentStep.run_id == state.run_id
            )
        ).all()
    return [StepEvidence(node_name=row.node_name, status=row.status) for row in rows]


def _cleanup_run(state: SupplierEOLWorkflowState) -> None:
    """Delete only records identified by this benchmark workflow state."""
    with create_session() as session:
        if state.run_id is not None:
            session.execute(delete(AuditEvent).where(AuditEvent.run_id == state.run_id))
            session.execute(delete(ToolCall).where(ToolCall.run_id == state.run_id))
            session.execute(delete(AgentStep).where(AgentStep.run_id == state.run_id))
            session.execute(delete(AgentRun).where(AgentRun.run_id == state.run_id))
        strategy_ids = list(
            session.scalars(
                select(ChangeStrategy.strategy_id).where(
                    ChangeStrategy.ecr_id == state.ecr_id
                )
            )
        )
        eco_ids = list(
            session.scalars(
                select(EngineeringChangeOrder.eco_id).where(
                    EngineeringChangeOrder.ecr_id == state.ecr_id
                )
            )
        )
        if eco_ids:
            session.execute(delete(ExecutionJob).where(ExecutionJob.eco_id.in_(eco_ids)))
            session.execute(
                delete(EngineeringChangeOrder).where(
                    EngineeringChangeOrder.eco_id.in_(eco_ids)
                )
            )
        if strategy_ids:
            session.execute(
                delete(ChangeStrategyAction).where(
                    ChangeStrategyAction.strategy_id.in_(strategy_ids)
                )
            )
            session.execute(
                delete(ChangeStrategy).where(ChangeStrategy.strategy_id.in_(strategy_ids))
            )
        if state.impact_id is not None:
            session.execute(
                delete(ChangeImpact).where(ChangeImpact.impact_id == state.impact_id)
            )
        if state.ecr_id is not None:
            session.execute(
                delete(EngineeringChangeRequest).where(
                    EngineeringChangeRequest.ecr_id == state.ecr_id
                )
            )
        if state.case_id is not None:
            session.execute(delete(ChangeCase).where(ChangeCase.case_id == state.case_id))
        session.commit()


def format_result(result: EvaluationResult) -> str:
    """Render the compact human-readable benchmark summary requested by the MVP."""
    lines = ["Supplier EOL Benchmark", ""]
    for metric in result.metrics.values():
        label = metric.name.replace("_", " ").title()
        lines.append(f"- {label}: {metric.score:.2f}")
    lines.extend(["", f"Overall: {result.score:.2f}", f"Passed: {str(result.passed).lower()}"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", choices=("fake", "deepseek"), default="fake")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    result = run_supplier_eol_benchmark(llm_mode=args.llm)
    print(result.model_dump_json(indent=2) if args.as_json else format_result(result))


if __name__ == "__main__":
    main()
