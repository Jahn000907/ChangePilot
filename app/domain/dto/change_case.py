"""Application DTOs for the minimal Supplier EOL ECM persistence flow."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.dto.eol_impact import SupplierEOLImpactResult


class SupplierEOLChangeCaseInput(BaseModel):
    """Supplier EOL event plus identifiers required by the current ECM model."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    case_number: str = Field(min_length=1, max_length=40)
    ecr_number: str = Field(min_length=1, max_length=40)
    idempotency_key: str = Field(min_length=1, max_length=100)
    supplier_code: str = Field(min_length=1, max_length=40)
    supplier_name: str = Field(min_length=1, max_length=200)
    part_number: str = Field(min_length=1, max_length=64)
    revision_code: str = Field(min_length=1, max_length=16)
    last_time_buy_date: date
    eol_date: date
    as_of_date: date
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    requested_by: str = Field(min_length=1, max_length=100)
    created_by: str = Field(min_length=1, max_length=100)
    source_type: str = Field(default="SUPPLIER_NOTICE", min_length=1, max_length=30)

    @field_validator("last_time_buy_date", "eol_date", "as_of_date", mode="before")
    @classmethod
    def _require_calendar_date(cls, value: object) -> object:
        if isinstance(value, datetime):
            raise ValueError(  # noqa: TRY004
                "event and analysis dates must be dates, not datetimes"
            )
        return value


class SupplierEOLChangeCaseResult(BaseModel):
    """Persisted ECM identifiers and the deterministic analysis result."""

    model_config = ConfigDict(frozen=True)

    case_id: uuid.UUID
    case_number: str
    case_status: str
    ecr_id: uuid.UUID
    ecr_number: str
    ecr_status: str
    impact_id: uuid.UUID
    analysis_run_id: uuid.UUID
    impact: SupplierEOLImpactResult
