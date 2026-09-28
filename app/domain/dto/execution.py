"""Result contracts for the minimal approved-strategy execution record."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExecutionResultStatus(StrEnum):
    """Status of the created downstream execution work."""

    PENDING = "PENDING"


class ExecutionResult(BaseModel):
    """Identifiers created by one atomic ECM execution-record transaction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: uuid.UUID
    eco_id: uuid.UUID
    execution_job_ids: list[uuid.UUID] = Field(min_length=1)
    status: ExecutionResultStatus
    summary: str = Field(min_length=1)
