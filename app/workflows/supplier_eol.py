"""Minimal LangGraph workflow for a Supplier EOL change event."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agents.execution import ExecutionAgent
from app.agents.impact import ImpactAgent
from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.domain.dto.approval import HumanApproval, HumanApprovalRequest
from app.domain.dto.change_case import SupplierEOLChangeCaseInput
from app.services.trace import TraceService
from app.workflows.human_approval import human_approval_node
from app.workflows.postgres_checkpoint import SUPPLIER_EOL_NAMESPACE, get_postgres_checkpointer
from app.workflows.state import (
    SupplierEOLWorkflowExecutionResult,
    SupplierEOLWorkflowState,
)

MAX_STRATEGY_REVISIONS = 2


def build_supplier_eol_workflow(
    *,
    impact_agent: ImpactAgent | None = None,
    strategy_agent: StrategyAgent | None = None,
    review_agent: ReviewAgent | None = None,
    execution_agent: ExecutionAgent | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    trace_service: TraceService | None = None,
):
    """Compile the Supplier EOL workflow with durable PostgreSQL checkpoints."""
    trace = trace_service or TraceService()
    review = review_agent or ReviewAgent(trace_service=trace)
    review.set_trace_service(trace)
    graph = StateGraph(SupplierEOLWorkflowState)
    graph.add_node(
        "impact_analysis",
        _traced_node("impact_analysis", "ImpactAgent", impact_agent or ImpactAgent(), trace),
    )
    graph.add_node(
        "strategy_generation",
        _traced_node(
            "strategy_generation",
            "StrategyAgent",
            strategy_agent or StrategyAgent(),
            trace,
        ),
    )
    graph.add_node("review", _traced_node("review", "ReviewAgent", review, trace))
    graph.add_node(
        "human_approval",
        _traced_node("human_approval", None, human_approval_node, trace),
    )
    graph.add_node(
        "execution",
        _traced_node("execution", "ExecutionAgent", execution_agent or ExecutionAgent(), trace),
    )
    graph.add_edge(START, "impact_analysis")
    graph.add_edge("impact_analysis", "strategy_generation")
    graph.add_edge("strategy_generation", "review")
    graph.add_conditional_edges(
        "review",
        _route_after_review,
        {
            "human_approval": "human_approval",
            "revision_limit": END,
            "revise": "strategy_generation",
        },
    )
    graph.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        {"approve": "execution", "reject": END},
    )
    graph.add_edge("execution", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else get_postgres_checkpointer())


def run_supplier_eol_workflow(
    input_event: SupplierEOLChangeCaseInput,
    *,
    thread_id: str,
    strategy_agent: StrategyAgent | None = None,
    review_agent: ReviewAgent | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    trace_service: TraceService | None = None,
) -> SupplierEOLWorkflowExecutionResult:
    """Start one thread and return its interrupted or completed state."""
    config = _thread_config(thread_id)
    trace = trace_service or TraceService()
    run_id = uuid.uuid4()
    trace.create_run(run_id)
    workflow = build_supplier_eol_workflow(
        strategy_agent=strategy_agent,
        review_agent=review_agent,
        checkpointer=checkpointer,
        trace_service=trace,
    )
    initial_state = SupplierEOLWorkflowState(run_id=run_id, input_event=input_event)
    try:
        workflow.invoke(initial_state, config)
    except Exception as exc:
        trace.update_run_status(run_id, "FAILED", error=str(exc)[:2000])
        raise
    result = _execution_result(workflow, config, thread_id)
    trace.update_run_status(
        run_id,
        "WAITING_HUMAN" if result.status == "INTERRUPTED" else "SUCCEEDED",
    )
    return result


def resume_supplier_eol_workflow(
    *,
    thread_id: str,
    approval: HumanApproval,
    checkpointer: BaseCheckpointSaver | None = None,
    trace_service: TraceService | None = None,
) -> SupplierEOLWorkflowExecutionResult:
    """Resume a paused approval node with a validated human decision."""
    config = _thread_config(thread_id)
    trace = trace_service or TraceService()
    workflow = build_supplier_eol_workflow(
        checkpointer=checkpointer,
        trace_service=trace,
    )
    saved_state = SupplierEOLWorkflowState.model_validate(workflow.get_state(config).values)
    if saved_state.run_id is None:
        raise ValueError("checkpointed workflow has no Agent Run identifier")
    trace.update_run_status(saved_state.run_id, "RUNNING", required=True)
    try:
        workflow.invoke(Command(resume=approval.model_dump(mode="json")), config)
    except Exception as exc:
        trace.update_run_status(saved_state.run_id, "FAILED", error=str(exc)[:2000])
        raise
    result = _execution_result(workflow, config, thread_id)
    trace.update_run_status(
        saved_state.run_id,
        "WAITING_HUMAN" if result.status == "INTERRUPTED" else "SUCCEEDED",
    )
    return result


def _route_after_review(state: SupplierEOLWorkflowState | dict[str, object]) -> str:
    """Route REVISE while the bounded number of regenerations remains."""
    workflow_state = SupplierEOLWorkflowState.model_validate(state)
    if workflow_state.review_result is None:
        raise ValueError("review node completed without a review result")
    if workflow_state.review_result.decision == "PASS":
        return "human_approval"
    if (
        workflow_state.review_result.decision == "REVISE"
        and workflow_state.revision_count >= MAX_STRATEGY_REVISIONS
    ):
        return "revision_limit"
    return "revise"


def _route_after_approval(state: SupplierEOLWorkflowState | dict[str, object]) -> str:
    """End the workflow after either supported human decision."""
    workflow_state = SupplierEOLWorkflowState.model_validate(state)
    if workflow_state.approval is None:
        raise ValueError("human approval node completed without an approval")
    return "approve" if workflow_state.approval.decision == "APPROVE" else "reject"


def _thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    normalized = thread_id.strip()
    if not normalized:
        raise ValueError("thread_id must not be empty")
    return {"configurable": {"thread_id": f"{SUPPLIER_EOL_NAMESPACE}:{normalized}"}}


def get_supplier_eol_workflow_result(
    thread_id: str, *, checkpointer: BaseCheckpointSaver | None = None,
) -> SupplierEOLWorkflowExecutionResult:
    """Reconstruct the public result from a checkpoint after any process restart."""
    config = _thread_config(thread_id)
    workflow = build_supplier_eol_workflow(checkpointer=checkpointer)
    if not workflow.get_state(config).values:
        raise LookupError("工作流 Checkpoint 不存在")
    return _execution_result(workflow, config, thread_id)


def _execution_result(
    workflow: object,
    config: dict[str, dict[str, str]],
    thread_id: str,
) -> SupplierEOLWorkflowExecutionResult:
    """Read checkpoint state and surface at most one approval interrupt."""
    snapshot = workflow.get_state(config)  # type: ignore[attr-defined]
    state = SupplierEOLWorkflowState.model_validate(snapshot.values)
    interrupts = [
        pending_interrupt
        for task in snapshot.tasks
        for pending_interrupt in task.interrupts
    ]
    if interrupts:
        pending = interrupts[0]
        return SupplierEOLWorkflowExecutionResult(
            thread_id=thread_id,
            status="INTERRUPTED",
            state=state,
            approval_request=HumanApprovalRequest.model_validate(pending.value),
            interrupt_id=pending.id,
        )
    return SupplierEOLWorkflowExecutionResult(
        thread_id=thread_id,
        status="COMPLETED",
        state=state,
    )


def _traced_node(
    node_name: str,
    agent_name: str | None,
    node: Callable[[SupplierEOLWorkflowState | dict[str, object]], dict[str, object]],
    trace: TraceService,
) -> Callable[[SupplierEOLWorkflowState | dict[str, object]], dict[str, object]]:
    """Wrap one graph node with required Step lifecycle records."""

    def invoke(
        state: SupplierEOLWorkflowState | dict[str, object],
    ) -> dict[str, object]:
        workflow_state = SupplierEOLWorkflowState.model_validate(state)
        if workflow_state.run_id is None:
            raise ValueError(f"{node_name} requires an Agent Run identifier")
        step_id, started_clock = trace.start_step(
            run_id=workflow_state.run_id,
            node_name=node_name,
            agent_name=agent_name,
            input_summary=_step_input_summary(node_name, workflow_state),
        )
        try:
            with trace.bind_step(step_id):
                output = node(workflow_state)
        except GraphInterrupt:
            trace.finish_step(
                step_id=step_id,
                started_clock=started_clock,
                status="WAITING_HUMAN",
                output_summary={"approval_status": "PENDING"},
            )
            raise
        except Exception as exc:
            trace.finish_step(
                step_id=step_id,
                started_clock=started_clock,
                status="FAILED",
                error=str(exc)[:2000],
            )
            raise

        updated_state = _state_with_update(workflow_state, output)
        if node_name == "impact_analysis" and updated_state.case_id is not None:
            trace.attach_case(workflow_state.run_id, updated_state.case_id)
        trace.finish_step(
            step_id=step_id,
            started_clock=started_clock,
            status="SUCCEEDED",
            output_summary=_step_output_summary(node_name, updated_state),
        )
        _record_audit_events(node_name, updated_state, trace)
        return output

    return invoke


def _state_with_update(
    state: SupplierEOLWorkflowState,
    update: dict[str, object],
) -> SupplierEOLWorkflowState:
    values = state.model_dump(mode="python")
    values.update(update)
    return SupplierEOLWorkflowState.model_validate(values)


def _step_input_summary(
    node_name: str,
    state: SupplierEOLWorkflowState,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "part_number": state.input_event.part_number,
        "revision_code": state.input_event.revision_code,
    }
    if state.case_id is not None:
        summary["case_id"] = str(state.case_id)
    if node_name in {"strategy_generation", "review"}:
        summary["strategy_count"] = len(state.strategies)
        summary["revision_count"] = state.revision_count
    if node_name in {"human_approval", "execution"}:
        summary["review_decision"] = (
            state.review_result.decision.value if state.review_result else None
        )
    if node_name == "execution":
        summary["approval_decision"] = (
            state.approval.decision.value if state.approval else None
        )
    return summary


def _step_output_summary(
    node_name: str,
    state: SupplierEOLWorkflowState,
) -> dict[str, object]:
    if node_name == "impact_analysis":
        return {
            "case_id": str(state.case_id),
            "ecr_id": str(state.ecr_id),
            "impact_id": str(state.impact_id),
        }
    if node_name == "strategy_generation":
        return {
            "strategy_count": len(state.strategies),
            "revision_count": state.revision_count,
        }
    if node_name == "review":
        return {
            "decision": state.review_result.decision.value if state.review_result else None,
            "issue_count": len(state.review_result.issues) if state.review_result else 0,
        }
    if node_name == "human_approval":
        return {
            "decision": state.approval.decision.value if state.approval else None,
            "reviewer": state.approval.reviewer if state.approval else None,
        }
    if node_name == "execution":
        return {
            "strategy_id": (
                str(state.execution_result.strategy_id) if state.execution_result else None
            ),
            "eco_id": str(state.execution_result.eco_id) if state.execution_result else None,
            "execution_job_count": (
                len(state.execution_result.execution_job_ids)
                if state.execution_result
                else 0
            ),
        }
    return {}


def _record_audit_events(
    node_name: str,
    state: SupplierEOLWorkflowState,
    trace: TraceService,
) -> None:
    if state.run_id is None:
        return
    if node_name == "impact_analysis" and state.case_id is not None:
        trace.audit(
            run_id=state.run_id,
            case_id=state.case_id,
            actor_type="AGENT",
            actor_id="ImpactAgent",
            action="CHANGE_CASE_CREATED",
            object_type="CHANGE_CASE",
            object_id=str(state.case_id),
            after_state={"case_number": state.case_number, "status": state.case_status},
            metadata={"ecr_id": str(state.ecr_id)},
        )
    elif node_name == "human_approval" and state.approval is not None:
        trace.audit(
            run_id=state.run_id,
            case_id=state.case_id,
            actor_type="HUMAN",
            actor_id=state.approval.reviewer or "anonymous-reviewer",
            action=f"HUMAN_{state.approval.decision.value}",
            object_type="CHANGE_CASE",
            object_id=str(state.case_id),
            after_state={
                "decision": state.approval.decision.value,
                "comment": state.approval.comment,
            },
            metadata={"selected_strategy_index": state.approval.selected_strategy_index},
        )
    elif node_name == "execution" and state.execution_result is not None:
        execution = state.execution_result
        common = {
            "run_id": state.run_id,
            "case_id": state.case_id,
            "actor_type": "AGENT",
            "actor_id": "ExecutionAgent",
        }
        trace.audit(
            **common,
            action="STRATEGY_SELECTED",
            object_type="CHANGE_STRATEGY",
            object_id=str(execution.strategy_id),
            after_state={"status": "SELECTED"},
        )
        trace.audit(
            **common,
            action="ECO_CREATED",
            object_type="ENGINEERING_CHANGE_ORDER",
            object_id=str(execution.eco_id),
            after_state={"status": "DRAFT"},
        )
        for execution_job_id in execution.execution_job_ids:
            trace.audit(
                **common,
                action="EXECUTION_JOB_CREATED",
                object_type="EXECUTION_JOB",
                object_id=str(execution_job_id),
                after_state={"status": "PENDING"},
            )
