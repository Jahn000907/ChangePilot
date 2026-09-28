"""Deterministic material-substitution impact and workflow contracts."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.dto.approval import HumanApproval, HumanApprovalRequest
from app.domain.dto.erp_facts import (
    InventoryFactResult,
    ProductionRequirementFactResult,
    PurchaseOrderFactResult,
)
from app.domain.dto.execution import ExecutionResult
from app.domain.dto.product_structure import WhereUsedResult
from app.domain.dto.review import ReviewResult
from app.domain.dto.strategy import StrategyCandidate


class MaterialSubstitutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    part_number: str = Field(min_length=1, max_length=64)
    revision_code: str = Field(min_length=1, max_length=16)
    candidate_part_number: str = Field(min_length=1, max_length=64)
    candidate_revision_code: str | None = Field(default=None, max_length=16)
    as_of_date: date
    requested_by: str = Field(default="api-client", min_length=1, max_length=100)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"

    @model_validator(mode="after")
    def _different_candidate(self) -> MaterialSubstitutionInput:
        if self.part_number == self.candidate_part_number and (
            self.candidate_revision_code is None
            or self.revision_code == self.candidate_revision_code
        ):
            raise ValueError("候选替代料不能与原零件相同")
        return self


class MaterialSubstitutionImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: str
    revision_code: str
    candidate_part_number: str
    candidate_revision_code: str
    as_of_date: date
    qualification_status: str
    replacement_type: str | None
    original_where_used: WhereUsedResult
    candidate_where_used: WhereUsedResult
    original_inventory: InventoryFactResult
    candidate_inventory: InventoryFactResult
    original_purchase: PurchaseOrderFactResult
    candidate_purchase: PurchaseOrderFactResult
    original_production: ProductionRequirementFactResult
    candidate_production: ProductionRequirementFactResult
    affected_products: list[str]
    caveats: list[str]


class MaterialSubstitutionCaseResult(BaseModel):
    case_id: uuid.UUID
    case_number: str
    ecr_id: uuid.UUID
    ecr_number: str
    impact_id: uuid.UUID
    impact: MaterialSubstitutionImpact


class MaterialSubstitutionWorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    thread_id: str
    input_event: MaterialSubstitutionInput
    case_id: uuid.UUID | None = None
    case_number: str | None = None
    ecr_id: uuid.UUID | None = None
    ecr_number: str | None = None
    impact_id: uuid.UUID | None = None
    impact: MaterialSubstitutionImpact | None = None
    strategies: list[StrategyCandidate] = Field(default_factory=list)
    review_result: ReviewResult | None = None
    revision_count: int = 0
    approval: HumanApproval | None = None
    approval_status: str = "NOT_STARTED"
    execution_result: ExecutionResult | None = None
    status: str = "RECEIVED"


class MaterialSubstitutionWorkflowResult(BaseModel):
    thread_id: str
    status: Literal["INTERRUPTED", "COMPLETED"]
    state: MaterialSubstitutionWorkflowState
    approval_request: HumanApprovalRequest | None = None
