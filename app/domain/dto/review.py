"""Structured result of reviewing generated Supplier EOL strategies."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReviewDecision(StrEnum):
    """Workflow route selected by a completed strategy review."""

    PASS = "PASS"
    REVISE = "REVISE"


class ReviewResult(BaseModel):
    """Evidence-bound review outcome used for conditional routing."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    decision: ReviewDecision
    summary: str = Field(min_length=1)
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
