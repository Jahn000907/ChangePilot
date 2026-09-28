"""Small, serializable contracts for the Supplier EOL benchmark."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SupplierEOLExpectedResult(BaseModel):
    """Accepted CASE-EOL-001 facts already established by the Golden Seed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    affected_finished_products: list[str] = Field(min_length=1)
    inventory_available_qty: Decimal
    purchase_committed_open_qty: Decimal
    purchase_order_count: int = Field(ge=0)
    production_frozen_demand_qty: Decimal
    production_order_count: int = Field(ge=0)
    alternatives: dict[str, str]
    expects_purchase_impact: bool
    expects_production_impact: bool


class SupplierEOLBenchmarkCase(BaseModel):
    """One benchmark definition that references, rather than copies, its event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    scenario_file: str = Field(min_length=1)
    as_of_date: date
    expected: SupplierEOLExpectedResult


class EvaluationMetric(BaseModel):
    """Result from one deterministic evaluator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    details: dict[str, object] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    """Aggregated, JSON-serializable benchmark outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    metrics: dict[str, EvaluationMetric]
    issues: list[str] = Field(default_factory=list)


class StepEvidence(BaseModel):
    """Minimum Agent Step history needed by the safety evaluators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_name: str
    status: str
