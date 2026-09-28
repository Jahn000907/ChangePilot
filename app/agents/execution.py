"""Deterministic Execution Agent for an approved strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.execution import ExecutionService

if TYPE_CHECKING:
    from app.workflows.state import SupplierEOLWorkflowState


class ExecutionAgent:
    """Select the approved candidate and delegate atomic ECM persistence."""

    def __init__(self, execution_service: ExecutionService | None = None) -> None:
        self._execution_service = execution_service or ExecutionService()

    def __call__(
        self,
        state: SupplierEOLWorkflowState | dict[str, object],
    ) -> dict[str, object]:
        """Persist execution records only after an explicit APPROVE decision."""
        from app.workflows.state import SupplierEOLWorkflowState

        workflow_state = SupplierEOLWorkflowState.model_validate(state)
        if workflow_state.approval is None or workflow_state.approval.decision != "APPROVE":
            raise ValueError("execution requires an APPROVE human decision")
        if workflow_state.ecr_id is None:
            raise ValueError("execution requires a persisted ECR identifier")
        selected_index = workflow_state.approval.selected_strategy_index
        if selected_index >= len(workflow_state.strategies):
            raise ValueError("selected_strategy_index is outside the candidate strategy list")

        result = self._execution_service.execute_approved_strategy(
            ecr_id=workflow_state.ecr_id,
            event=workflow_state.input_event,
            strategy=workflow_state.strategies[selected_index],
            approval=workflow_state.approval,
        )
        return {
            "execution_result": result,
            "execution_status": "COMPLETED",
            "status": "COMPLETED",
            "error": None,
        }
