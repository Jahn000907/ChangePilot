"""Stable request contracts for the minimal Supplier EOL HTTP API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StartSupplierEOLWorkflowRequest(BaseModel):
    """External Supplier EOL event accepted by the workflow endpoint."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    thread_id: str = Field(min_length=1, max_length=64)
    part_number: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=16)
    supplier_code: str = Field(min_length=1, max_length=40)
    supplier_name: str = Field(min_length=1, max_length=200)
    last_time_buy_date: date
    eol_date: date
    as_of_date: date
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    requested_by: str = Field(default="api-client", min_length=1, max_length=100)
    source_type: str = Field(default="SUPPLIER_NOTICE", min_length=1, max_length=30)


class HealthResponse(BaseModel):
    """Process liveness response without backend checks."""

    status: Literal["ok"] = "ok"
