"""LLM-backed Strategy Agent for confirmed Supplier EOL impact facts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.domain.dto.strategy import StrategyGenerationResult
from app.llm.client import DeepSeekLLMClient, LLMClient

if TYPE_CHECKING:
    from app.workflows.state import SupplierEOLWorkflowState


_SYSTEM_PROMPT = """You generate advisory engineering strategies for a Supplier EOL event.
Use only the supplied facts. Never invent inventory, orders, BOM relationships, dates, or
qualification status. Only alternatives classified ELIGIBLE may be treated as qualified;
REQUIRES_REVIEW needs validation, and INELIGIBLE must not be presented as qualified. Return
only one JSON object with a non-empty `strategies` array. Each item must contain:
strategy_type, title, summary, rationale, actions, risks.
strategy_type must be one of LAST_TIME_BUY, QUALIFIED_ALTERNATIVE, QUALIFICATION_REQUIRED,
REDESIGN, SUPPLY_MITIGATION. Provide candidates, not a final approval decision."""


class StrategyAgent:
    """Generate validated strategy candidates without querying or mutating data."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    def __call__(
        self,
        state: SupplierEOLWorkflowState | dict[str, object],
    ) -> dict[str, object]:
        """Send selected impact facts to the LLM and validate its JSON response."""
        from app.workflows.state import SupplierEOLWorkflowState

        workflow_state = SupplierEOLWorkflowState.model_validate(state)
        if workflow_state.impact is None:
            raise ValueError("strategy_generation requires a completed impact result")

        facts = self._strategy_facts(workflow_state)
        is_revision = (
            workflow_state.review_result is not None
            and workflow_state.review_result.decision == "REVISE"
        )
        if is_revision:
            facts["review_feedback"] = workflow_state.review_result.model_dump(mode="json")
        result = self.generate_from_facts(facts)
        return {
            "strategies": result.strategies,
            "strategy_status": "COMPLETED",
            "review_status": "NOT_STARTED",
            "revision_count": (
                workflow_state.revision_count + 1
                if is_revision
                else workflow_state.revision_count
            ),
            "status": "COMPLETED",
            "error": None,
        }

    def generate_from_facts(
        self, facts: dict[str, object], *, system_prompt: str = _SYSTEM_PROMPT
    ) -> StrategyGenerationResult:
        """Shared evidence-to-strategy boundary for supported change scenarios."""
        client = self._llm_client or DeepSeekLLMClient()
        raw_response = client.generate_json(
            system_prompt=system_prompt,
            user_prompt=("Generate candidate strategies from this JSON fact set:\n"
                         + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))),
        )
        return StrategyGenerationResult.model_validate_json(raw_response)

    @staticmethod
    def _strategy_facts(state: SupplierEOLWorkflowState) -> dict[str, object]:
        """Select decision-relevant facts while excluding verbose raw evidence."""
        impact = state.impact
        if impact is None:  # Kept local for type narrowing; guarded by ``__call__``.
            raise ValueError("strategy facts require an impact result")

        event = state.input_event
        return {
            "event": {
                "supplier_code": event.supplier_code,
                "supplier_name": event.supplier_name,
                "part_number": event.part_number,
                "revision_code": event.revision_code,
                "last_time_buy_date": event.last_time_buy_date.isoformat(),
                "eol_date": event.eol_date.isoformat(),
                "as_of_date": event.as_of_date.isoformat(),
            },
            "affected_products": impact.product.affected_finished_products,
            "requirement_per_product": impact.bom_quantity.model_dump(
                mode="json",
                include={"requirement_per_product", "products_without_requirement"},
            ),
            "inventory": impact.inventory.model_dump(mode="json"),
            "purchase": impact.purchase.model_dump(
                mode="json",
                include={
                    "committed_open_qty",
                    "potential_qty",
                    "blocked_qty",
                    "timing_counts",
                },
            ),
            "production": impact.production.model_dump(
                mode="json",
                include={
                    "current_frozen_demand_qty",
                    "remaining_by_product",
                },
            ),
            "sales": impact.sales.model_dump(
                mode="json",
                include={
                    "current_exposure_orders",
                    "current_exposure_qty",
                    "potential_exposure_orders",
                    "potential_exposure_qty",
                    "material_equivalent",
                },
            ),
            "alternatives": impact.alternatives.model_dump(mode="json"),
            "coverage": impact.coverage.model_dump(mode="json"),
            "caveats": list(impact.caveats),
        }
