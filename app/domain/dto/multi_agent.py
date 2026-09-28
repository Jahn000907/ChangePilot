"""Structured contracts for bounded cross-domain assistant collaboration."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainName(StrEnum):
    STRUCTURE = "StructureAgent"
    SUPPLY = "SupplyAgent"
    PRODUCTION = "ProductionAgent"
    DELIVERY = "DeliveryAgent"


class DomainAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: DomainName
    task: str = Field(min_length=1, max_length=300)
    tools: list[str] = Field(default_factory=list, max_length=5)


class SupervisorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multi_agent: bool
    agents: list[DomainAssignment] = Field(default_factory=list, max_length=4)


class DomainEvidence(BaseModel):
    tool_name: str
    arguments: dict[str, object]
    summary: str


class DomainAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: DomainName
    task: str
    status: Literal["SUCCESS", "PARTIAL", "NO_DATA", "FAILED"]
    facts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    evidence: list[DomainEvidence] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)


class SupervisorSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgment: str
    recommendations: list[str] = Field(default_factory=list, max_length=5)


class MultiAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_agents: list[DomainName]
    domains: list[DomainAgentResult]
    judgment: str
    recommendations: list[str]
    status: Literal["SUCCESS", "PARTIAL", "FAILED"]
