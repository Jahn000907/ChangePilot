"""Human approval contracts for the interrupted Supplier EOL workflow."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.dto.review import ReviewResult
from app.domain.dto.strategy import StrategyCandidate


class ApprovalDecision(StrEnum):
    """Human decisions supported by the first approval gate."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class HumanApproval(BaseModel):
    """Validated response supplied when resuming an interrupted graph."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    decision: ApprovalDecision
    comment: str = ""
    reviewer: str | None = Field(default=None, min_length=1, max_length=100)
    selected_strategy_index: int = Field(default=0, ge=0)


class HumanApprovalRequest(BaseModel):
    """Minimum context shown to the human at the approval interrupt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: uuid.UUID
    case_number: str
    ecr_id: uuid.UUID
    ecr_number: str
    impact_summary: dict[str, object]
    strategies: list[StrategyCandidate] = Field(min_length=1)
    review_result: ReviewResult
    review_exhausted: bool = False
    human_intervention_reason: str | None = None
