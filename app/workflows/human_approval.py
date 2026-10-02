"""LangGraph interrupt node for the human approval gate."""

from __future__ import annotations

from langgraph.types import interrupt

from app.domain.dto.approval import HumanApproval, HumanApprovalRequest
from app.workflows.state import SupplierEOLWorkflowState


def human_approval_node(
    state: SupplierEOLWorkflowState | dict[str, object],
) -> dict[str, object]:
    """Pause with approval context and validate the value supplied on resume."""
    workflow_state = SupplierEOLWorkflowState.model_validate(state)
    request = _approval_request(workflow_state)
    response = interrupt(request.model_dump(mode="json"))
    approval = HumanApproval.model_validate(response)
    return {
        "approval": approval,
        "approval_status": "COMPLETED",
        "status": "COMPLETED",
        "error": None,
    }


def _approval_request(state: SupplierEOLWorkflowState) -> HumanApprovalRequest:
    """Select the minimum persisted and analytical context needed to decide."""
    if (
        state.case_id is None
        or state.case_number is None
        or state.ecr_id is None
        or state.ecr_number is None
    ):
        raise ValueError("human approval requires persisted Change Case and ECR identifiers")
    if state.impact is None or state.review_result is None or not state.strategies:
        raise ValueError("human approval requires impact, strategies and review result")

    impact = state.impact
    return HumanApprovalRequest(
        case_id=state.case_id,
        case_number=state.case_number,
        ecr_id=state.ecr_id,
        ecr_number=state.ecr_number,
        impact_summary={
            "part_number": impact.part_number,
            "revision_code": impact.revision_code,
            "affected_products": impact.product.affected_finished_products,
            "available_inventory": str(impact.inventory.available_qty),
            "committed_open_purchase_qty": str(impact.purchase.committed_open_qty),
            "current_frozen_production_demand": str(
                impact.production.current_frozen_demand_qty
            ),
            "projected_coverage_delta": str(impact.coverage.projected_coverage_delta),
            "eligible_alternatives": impact.alternatives.eligible_count,
            "alternatives_requiring_review": impact.alternatives.requires_review_count,
        },
        strategies=state.strategies,
        review_result=state.review_result,
        review_exhausted=state.review_exhausted,
        human_intervention_reason=(
            "自动策略修订已达到上限，当前评审仍存在问题，需要人工决定。"
            if state.review_exhausted else None
        ),
    )
