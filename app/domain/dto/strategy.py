"""Structured candidate strategies produced from confirmed impact facts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrategyType(StrEnum):
    """Small strategy vocabulary supported by the first Strategy Agent."""

    LAST_TIME_BUY = "LAST_TIME_BUY"
    QUALIFIED_ALTERNATIVE = "QUALIFIED_ALTERNATIVE"
    QUALIFICATION_REQUIRED = "QUALIFICATION_REQUIRED"
    REDESIGN = "REDESIGN"
    SUPPLY_MITIGATION = "SUPPLY_MITIGATION"


class StrategyCandidate(BaseModel):
    """One advisory engineering response candidate, not an approval decision."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    strategy_type: StrategyType
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    actions: list[str] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)


class StrategyGenerationResult(BaseModel):
    """Validated envelope for one or more strategy candidates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategies: list[StrategyCandidate] = Field(min_length=1)
