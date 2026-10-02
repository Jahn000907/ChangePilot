"""State model for the minimal Supplier EOL workflow."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.dto.approval import HumanApproval, HumanApprovalRequest
from app.domain.dto.change_case import SupplierEOLChangeCaseInput
from app.domain.dto.eol_impact import SupplierEOLImpactResult
from app.domain.dto.execution import ExecutionResult
from app.domain.dto.review import ReviewResult
from app.domain.dto.strategy import StrategyCandidate


class SupplierEOLWorkflowStatus(StrEnum):
    """Execution states exposed by the first Supplier EOL workflow."""

    RECEIVED = "RECEIVED"
    COMPLETED = "COMPLETED"


class StrategyGenerationStatus(StrEnum):
    """Progress of the optional LLM strategy step."""

    NOT_STARTED = "NOT_STARTED"
    COMPLETED = "COMPLETED"


class ReviewStatus(StrEnum):
    """Progress of the strategy review step."""

    NOT_STARTED = "NOT_STARTED"
    COMPLETED = "COMPLETED"


class ApprovalStatus(StrEnum):
    """Progress of the human approval gate."""

    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class WorkflowRunStatus(StrEnum):
    """Whether a public workflow invocation paused or finished."""

    RUNNING = "RUNNING"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExecutionStatus(StrEnum):
    """Progress of the deterministic execution-record step."""

    NOT_STARTED = "NOT_STARTED"
    COMPLETED = "COMPLETED"


class SupplierEOLWorkflowState(BaseModel):
    """Serializable state shared by the Supplier EOL graph and its node."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID | None = None
    input_event: SupplierEOLChangeCaseInput
    case_id: uuid.UUID | None = None
    case_number: str | None = None
    case_status: str | None = None
    ecr_id: uuid.UUID | None = None
    ecr_number: str | None = None
    ecr_status: str | None = None
    impact_id: uuid.UUID | None = None
    analysis_run_id: uuid.UUID | None = None
    impact: SupplierEOLImpactResult | None = None
    strategies: list[StrategyCandidate] = Field(default_factory=list)
    strategy_status: StrategyGenerationStatus = StrategyGenerationStatus.NOT_STARTED
    review_result: ReviewResult | None = None
    review_status: ReviewStatus = ReviewStatus.NOT_STARTED
    review_count: int = Field(default=0, ge=0)
    review_exhausted: bool = False
    revision_count: int = Field(default=0, ge=0)
    approval: HumanApproval | None = None
    approval_status: ApprovalStatus = ApprovalStatus.NOT_STARTED
    execution_result: ExecutionResult | None = None
    execution_status: ExecutionStatus = ExecutionStatus.NOT_STARTED
    status: SupplierEOLWorkflowStatus = SupplierEOLWorkflowStatus.RECEIVED
    error: str | None = None


class SupplierEOLWorkflowExecutionResult(BaseModel):
    """Stable public result for both interrupted and completed invocations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str = Field(min_length=1)
    status: WorkflowRunStatus
    state: SupplierEOLWorkflowState
    approval_request: HumanApprovalRequest | None = None
    interrupt_id: str | None = None
