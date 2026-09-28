"""Deterministic Impact Agent node for the Supplier EOL workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.change_case import ChangeCaseService

if TYPE_CHECKING:
    from app.workflows.state import SupplierEOLWorkflowState


class ImpactAgent:
    """Run the existing ECM application service and map its result to state."""

    def __init__(self, change_case_service: ChangeCaseService | None = None) -> None:
        self._change_case_service = change_case_service or ChangeCaseService()

    def __call__(
        self,
        state: SupplierEOLWorkflowState | dict[str, object],
    ) -> dict[str, object]:
        """Persist the Supplier EOL analysis and return a partial state update."""
        from app.workflows.state import SupplierEOLWorkflowState

        workflow_state = SupplierEOLWorkflowState.model_validate(state)
        result = self._change_case_service.create_supplier_eol_change_case(
            workflow_state.input_event
        )
        return {
            "case_id": result.case_id,
            "case_number": result.case_number,
            "case_status": result.case_status,
            "ecr_id": result.ecr_id,
            "ecr_number": result.ecr_number,
            "ecr_status": result.ecr_status,
            "impact_id": result.impact_id,
            "analysis_run_id": result.analysis_run_id,
            "impact": result.impact,
            "status": "COMPLETED",
            "error": None,
        }
