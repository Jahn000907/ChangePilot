"""Material substitution graph using the existing ECM and agent boundaries."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.domain.dto.approval import HumanApproval, HumanApprovalRequest
from app.domain.dto.material_substitution import (
    MaterialSubstitutionInput,
    MaterialSubstitutionWorkflowResult,
    MaterialSubstitutionWorkflowState,
)
from app.domain.dto.review import ReviewResult
from app.domain.dto.strategy import StrategyType
from app.services.change_case import ChangeCaseService
from app.services.execution import ExecutionService
from app.services.trace import TraceService
from app.tools.langchain import get_enterprise_tools
from app.workflows.postgres_checkpoint import (
    MATERIAL_SUBSTITUTION_NAMESPACE,
    get_postgres_checkpointer,
)

MAX_STRATEGY_REVISIONS = 2
_STRATEGY_PROMPT = """Generate candidate engineering strategies for a material substitution.
Use only the supplied deterministic facts. The candidate part's qualification_status is
authoritative: UNQUALIFIED, CONDITIONAL and NOT_LISTED must not be described as ready for
direct substitution. Never invent inventory, procurement, BOM, or production quantities.
This is a material-substitution request, not an EOL notice. Do not propose LAST_TIME_BUY
unless the supplied facts explicitly contain an EOL or last-time-buy date. For a QUALIFIED
candidate, propose validation, controlled planning and human approval before switching;
do not claim that ERP or BOM has already been changed.
Return only JSON object {"strategies":[{"strategy_type":"QUALIFIED_ALTERNATIVE",
"title":"...","summary":"...","rationale":"...","actions":["..."],"risks":["..."]}]}.
Allowed strategy_type: QUALIFIED_ALTERNATIVE, QUALIFICATION_REQUIRED, REDESIGN,
SUPPLY_MITIGATION, LAST_TIME_BUY. Do not make final approval decisions."""
_REVIEW_PROMPT = """Review material substitution strategies against the supplied facts.
In particular, never permit direct adoption of an UNQUALIFIED, CONDITIONAL or NOT_LISTED
candidate. Verify uncertain business facts only with provided read-only Tools. Do not write.
Future validation actions are proposals, not claims that validation has already happened.
PASS when factual claims are grounded and the strategy keeps approval and execution gated;
do not require human approval to have happened before this review.
Return JSON only: {"decision":"PASS|REVISE","summary":"...","issues":[],"recommendations":[]}.
PASS means suitable for later human consideration, not approval."""


def build_material_substitution_workflow(
    *, strategy_agent: StrategyAgent | None = None,
    review_agent: ReviewAgent | None = None,
    change_case_service: ChangeCaseService | None = None,
    execution_service: ExecutionService | None = None,
    trace_service: TraceService | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    trace = trace_service or TraceService()
    strategy = strategy_agent or StrategyAgent()
    review = review_agent or ReviewAgent(tools=get_enterprise_tools(), trace_service=trace)
    review.set_trace_service(trace)
    cases = change_case_service or ChangeCaseService()
    execution = execution_service or ExecutionService()

    def impact_node(state: MaterialSubstitutionWorkflowState) -> dict[str, object]:
        result = cases.create_material_substitution_change_case(
            state.input_event, thread_id=state.thread_id
        )
        trace.attach_case(state.run_id, result.case_id)
        trace.audit(
            run_id=state.run_id, case_id=result.case_id,
            actor_type="AGENT", actor_id="MaterialSubstitutionImpact",
            action="CHANGE_CASE_CREATED", object_type="CHANGE_CASE",
            object_id=str(result.case_id),
        )
        return {
            "case_id": result.case_id, "case_number": result.case_number,
            "ecr_id": result.ecr_id, "ecr_number": result.ecr_number,
            "impact_id": result.impact_id, "impact": result.impact, "status": "IMPACT_COMPLETE",
        }

    def strategy_node(state: MaterialSubstitutionWorkflowState) -> dict[str, object]:
        if state.impact is None:
            raise ValueError("物料替代策略需要已完成的影响分析")
        facts = {"scenario": "material_substitution", "impact": state.impact.model_dump(mode="json")}
        revising = state.review_result is not None and state.review_result.decision == "REVISE"
        if revising:
            facts["review_feedback"] = state.review_result.model_dump(mode="json")
        result = strategy.generate_from_facts(facts, system_prompt=_STRATEGY_PROMPT)
        return {
            "strategies": result.strategies,
            "revision_count": state.revision_count + (1 if revising else 0),
            "status": "STRATEGY_COMPLETE",
        }

    def review_node(state: MaterialSubstitutionWorkflowState) -> dict[str, object]:
        if state.impact is None or not state.strategies:
            raise ValueError("策略评审需要影响分析和候选策略")
        if state.impact.qualification_status != "QUALIFIED" and any(
            item.strategy_type == StrategyType.QUALIFIED_ALTERNATIVE
            for item in state.strategies
        ):
            result = ReviewResult(
                decision="REVISE", summary="候选料未获已认证资格，不能直接切换。",
                issues=["QUALIFIED_ALTERNATIVE 与真实资格状态不符"],
                recommendations=["改为资格验证策略，或选择已认证候选料。"],
            )
        else:
            result = review.review_facts(
                impact=state.impact.model_dump(mode="json"),
                strategies=[item.model_dump(mode="json") for item in state.strategies],
                run_id=state.run_id, system_prompt=_REVIEW_PROMPT,
            )
        return {"review_result": result, "status": "REVIEW_COMPLETE"}

    def approval_node(state: MaterialSubstitutionWorkflowState) -> dict[str, object]:
        if not state.impact or not state.review_result or not state.strategies:
            raise ValueError("人工审批需要完整的影响与评审结果")
        if not state.case_id or not state.case_number or not state.ecr_id or not state.ecr_number:
            raise ValueError("人工审批需要持久化的 Case / ECR")
        request = HumanApprovalRequest(
            case_id=state.case_id, case_number=state.case_number,
            ecr_id=state.ecr_id, ecr_number=state.ecr_number,
            impact_summary={
                "part_number": state.impact.part_number,
                "revision_code": state.impact.revision_code,
                "candidate_part_number": state.impact.candidate_part_number,
                "candidate_revision_code": state.impact.candidate_revision_code,
                "qualification_status": state.impact.qualification_status,
                "affected_products": state.impact.affected_products,
            },
            strategies=state.strategies, review_result=state.review_result,
        )
        approval = HumanApproval.model_validate(interrupt(request.model_dump(mode="json")))
        trace.audit(
            run_id=state.run_id, case_id=state.case_id,
            actor_type="HUMAN", actor_id=approval.reviewer or "anonymous-reviewer",
            action=f"HUMAN_{approval.decision.value}", object_type="CHANGE_CASE",
            object_id=str(state.case_id),
            after_state={"decision": approval.decision.value},
        )
        return {"approval": approval, "approval_status": "COMPLETED", "status": "APPROVED" if approval.decision == "APPROVE" else "REJECTED"}

    def execution_node(state: MaterialSubstitutionWorkflowState) -> dict[str, object]:
        if state.approval is None or state.approval.decision != "APPROVE":
            raise ValueError("仅人工批准后可创建执行记录")
        if state.ecr_id is None or state.impact is None:
            raise ValueError("执行需要已持久化的 ECR 与影响分析")
        if state.approval.selected_strategy_index >= len(state.strategies):
            raise ValueError("所选策略不在候选范围内")
        result = execution.execute_approved_substitution(
            ecr_id=state.ecr_id, event=state.input_event,
            candidate_revision_code=state.impact.candidate_revision_code,
            strategy=state.strategies[state.approval.selected_strategy_index],
            approval=state.approval,
        )
        trace.audit(
            run_id=state.run_id, case_id=state.case_id,
            actor_type="AGENT", actor_id="ExecutionAgent",
            action="STRATEGY_SELECTED", object_type="CHANGE_STRATEGY",
            object_id=str(result.strategy_id),
        )
        trace.audit(
            run_id=state.run_id, case_id=state.case_id,
            actor_type="AGENT", actor_id="ExecutionAgent",
            action="ECO_CREATED", object_type="ENGINEERING_CHANGE_ORDER",
            object_id=str(result.eco_id),
        )
        for job_id in result.execution_job_ids:
            trace.audit(
                run_id=state.run_id, case_id=state.case_id,
                actor_type="AGENT", actor_id="ExecutionAgent",
                action="EXECUTION_JOB_CREATED", object_type="EXECUTION_JOB",
                object_id=str(job_id),
            )
        return {"execution_result": result, "status": "COMPLETED"}

    graph = StateGraph(MaterialSubstitutionWorkflowState)
    for name, node in (
        ("impact_analysis", impact_node),
        ("strategy_generation", strategy_node),
        ("review", review_node),
        ("human_approval", approval_node),
        ("execution", execution_node),
    ):
        graph.add_node(name, _traced(name, node, trace))
    graph.add_edge(START, "impact_analysis")
    graph.add_edge("impact_analysis", "strategy_generation")
    graph.add_edge("strategy_generation", "review")
    graph.add_conditional_edges("review", _after_review, {
        "revise": "strategy_generation", "approve": "human_approval", "end": END,
    })
    graph.add_conditional_edges("human_approval", _after_approval, {
        "execute": "execution", "end": END,
    })
    graph.add_edge("execution", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else get_postgres_checkpointer())


def run_material_substitution_workflow(
    event: MaterialSubstitutionInput, *, thread_id: str,
    strategy_agent: StrategyAgent | None = None,
    review_agent: ReviewAgent | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    trace_service: TraceService | None = None,
) -> MaterialSubstitutionWorkflowResult:
    trace = trace_service or TraceService()
    run_id = uuid.uuid4()
    trace.create_run(run_id, workflow_name="material_substitution")
    graph = build_material_substitution_workflow(
        strategy_agent=strategy_agent, review_agent=review_agent,
        checkpointer=checkpointer, trace_service=trace,
    )
    config = _config(thread_id)
    try:
        graph.invoke(MaterialSubstitutionWorkflowState(
            run_id=run_id, thread_id=thread_id, input_event=event
        ), config)
    except Exception as exc:
        trace.update_run_status(run_id, "FAILED", error=str(exc)[:500])
        raise
    result = _result(graph, config, thread_id)
    trace.update_run_status(run_id, "WAITING_HUMAN" if result.status == "INTERRUPTED" else "SUCCEEDED")
    return result


def resume_material_substitution_workflow(
    *, thread_id: str, approval: HumanApproval,
    checkpointer: BaseCheckpointSaver | None = None,
    trace_service: TraceService | None = None,
) -> MaterialSubstitutionWorkflowResult:
    trace = trace_service or TraceService()
    graph = build_material_substitution_workflow(checkpointer=checkpointer, trace_service=trace)
    config = _config(thread_id)
    state = MaterialSubstitutionWorkflowState.model_validate(graph.get_state(config).values)
    trace.update_run_status(state.run_id, "RUNNING", required=True)
    try:
        graph.invoke(Command(resume=approval.model_dump(mode="json")), config)
    except Exception as exc:
        trace.update_run_status(state.run_id, "FAILED", error=str(exc)[:500])
        raise
    result = _result(graph, config, thread_id)
    trace.update_run_status(state.run_id, "SUCCEEDED")
    return result


def _after_review(state: MaterialSubstitutionWorkflowState | dict[str, object]) -> str:
    parsed = MaterialSubstitutionWorkflowState.model_validate(state)
    if parsed.review_result is None:
        raise ValueError("缺少评审结果")
    if parsed.review_result.decision == "PASS":
        return "approve"
    return "end" if parsed.revision_count >= MAX_STRATEGY_REVISIONS else "revise"


def _after_approval(state: MaterialSubstitutionWorkflowState | dict[str, object]) -> str:
    parsed = MaterialSubstitutionWorkflowState.model_validate(state)
    return "execute" if parsed.approval and parsed.approval.decision == "APPROVE" else "end"


def _traced(
    name: str, node: Callable[[MaterialSubstitutionWorkflowState], dict[str, object]],
    trace: TraceService,
) -> Callable[[MaterialSubstitutionWorkflowState | dict[str, object]], dict[str, object]]:
    def invoke(state: MaterialSubstitutionWorkflowState | dict[str, object]) -> dict[str, object]:
        parsed = MaterialSubstitutionWorkflowState.model_validate(state)
        step_id, clock = trace.start_step(
            run_id=parsed.run_id, node_name=name, agent_name=name,
            input_summary={"part_number": parsed.input_event.part_number,
                           "candidate_part_number": parsed.input_event.candidate_part_number},
        )
        try:
            with trace.bind_step(step_id):
                output = node(parsed)
        except GraphInterrupt:
            trace.finish_step(step_id=step_id, started_clock=clock, status="WAITING_HUMAN")
            raise
        except Exception as exc:
            trace.finish_step(step_id=step_id, started_clock=clock,
                              status="FAILED", error=str(exc)[:500])
            raise
        trace.finish_step(step_id=step_id, started_clock=clock, status="SUCCEEDED",
                          output_summary={"status": str(output.get("status", "COMPLETED"))})
        return output
    return invoke


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    if not thread_id.strip():
        raise ValueError("thread_id 不能为空")
    return {"configurable": {"thread_id": f"{MATERIAL_SUBSTITUTION_NAMESPACE}:{thread_id.strip()}"}}


def get_material_substitution_workflow_result(
    thread_id: str, *, checkpointer: BaseCheckpointSaver | None = None,
) -> MaterialSubstitutionWorkflowResult:
    """Read the saved graph state without relying on an HTTP process cache."""
    config = _config(thread_id)
    graph = build_material_substitution_workflow(checkpointer=checkpointer)
    if not graph.get_state(config).values:
        raise LookupError("工作流 Checkpoint 不存在")
    return _result(graph, config, thread_id)


def _result(graph: object, config: dict[str, dict[str, str]], thread_id: str) -> MaterialSubstitutionWorkflowResult:
    snapshot = graph.get_state(config)  # type: ignore[attr-defined]
    state = MaterialSubstitutionWorkflowState.model_validate(snapshot.values)
    interrupts = [item for task in snapshot.tasks for item in task.interrupts]
    if interrupts:
        return MaterialSubstitutionWorkflowResult(
            thread_id=thread_id, status="INTERRUPTED", state=state,
            approval_request=HumanApprovalRequest.model_validate(interrupts[0].value),
        )
    return MaterialSubstitutionWorkflowResult(thread_id=thread_id, status="COMPLETED", state=state)
