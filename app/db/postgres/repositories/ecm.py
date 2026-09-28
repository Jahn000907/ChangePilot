"""Minimal PostgreSQL writes for the Supplier EOL ECM persistence flow."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres.models.ecm import (
    ChangeCase,
    ChangeImpact,
    ChangeStrategy,
    ChangeStrategyAction,
    EngineeringChangeOrder,
    EngineeringChangeRequest,
    ExecutionJob,
)


@dataclass(frozen=True)
class ChangeCaseRecord:
    case_id: uuid.UUID
    case_number: str
    status: str


@dataclass(frozen=True)
class EngineeringChangeRequestRecord:
    ecr_id: uuid.UUID
    ecr_number: str
    case_id: uuid.UUID
    status: str


@dataclass(frozen=True)
class ChangeImpactRecord:
    impact_id: uuid.UUID
    ecr_id: uuid.UUID
    analysis_run_id: uuid.UUID
    evidence: dict[str, Any]


@dataclass(frozen=True)
class ChangeStrategyRecord:
    strategy_id: uuid.UUID
    ecr_id: uuid.UUID
    strategy_code: str
    status: str


@dataclass(frozen=True)
class ChangeStrategyActionRecord:
    action_id: uuid.UUID
    strategy_id: uuid.UUID
    sequence_no: int


@dataclass(frozen=True)
class EngineeringChangeOrderRecord:
    eco_id: uuid.UUID
    ecr_id: uuid.UUID
    selected_strategy_id: uuid.UUID
    status: str


@dataclass(frozen=True)
class ExecutionJobRecord:
    execution_job_id: uuid.UUID
    eco_id: uuid.UUID
    status: str


class ECMRepository:
    """Minimal ECM persistence operations used by application services."""

    def case_id_for_ecr(self, ecr_id: uuid.UUID) -> uuid.UUID:
        case_id = self._session.scalar(
            select(EngineeringChangeRequest.case_id).where(
                EngineeringChangeRequest.ecr_id == ecr_id
            )
        )
        if case_id is None:
            raise LookupError("ECR 不存在，无法创建执行任务")
        return case_id

    def get_execution_for_ecr(
        self, ecr_id: uuid.UUID,
    ) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]] | None:
        """Find a committed execution before replaying an approval after a crash."""
        eco = self._session.scalar(
            select(EngineeringChangeOrder).where(EngineeringChangeOrder.ecr_id == ecr_id)
        )
        if eco is None:
            return None
        job_ids = list(self._session.scalars(
            select(ExecutionJob.execution_job_id).where(ExecutionJob.eco_id == eco.eco_id)
        ))
        if not job_ids:
            raise ValueError("现有 ECO 缺少执行任务，无法安全重复执行")
        return eco.selected_strategy_id, eco.eco_id, job_ids

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_change_case(
        self,
        *,
        case_id: uuid.UUID,
        case_number: str,
        raw_event: dict[str, Any],
        idempotency_key: str,
        source_type: str,
        created_by: str,
        case_type: str = "SUPPLIER_EOL",
    ) -> ChangeCaseRecord:
        row = ChangeCase(
            case_id=case_id,
            case_number=case_number,
            case_type=case_type,
            status="PLANNING",
            source_type=source_type,
            raw_event=raw_event,
            idempotency_key=idempotency_key,
            created_by=created_by,
        )
        self._session.add(row)
        self._session.flush()
        return ChangeCaseRecord(row.case_id, row.case_number, row.status)

    def create_engineering_change_request(
        self,
        *,
        ecr_id: uuid.UUID,
        ecr_number: str,
        case_id: uuid.UUID,
        source_type: str,
        part_number: str,
        revision_code: str,
        title: str,
        description: str,
        priority: str,
        requested_by: str,
        change_type: str = "SUPPLIER_EOL",
    ) -> EngineeringChangeRequestRecord:
        row = EngineeringChangeRequest(
            ecr_id=ecr_id,
            ecr_number=ecr_number,
            case_id=case_id,
            change_type=change_type,
            source_type=source_type,
            subject_part_number=part_number,
            subject_revision_code=revision_code,
            title=title,
            description=description,
            priority=priority,
            status="PLANNING",
            requested_by=requested_by,
        )
        self._session.add(row)
        self._session.flush()
        return EngineeringChangeRequestRecord(
            row.ecr_id, row.ecr_number, row.case_id, row.status
        )

    def create_change_impact(
        self,
        *,
        impact_id: uuid.UUID,
        ecr_id: uuid.UUID,
        analysis_run_id: uuid.UUID,
        object_key: str,
        evidence: dict[str, Any],
        impact_type: str = "SUPPLIER_EOL_ANALYSIS",
        reason: str = "Deterministic Supplier EOL impact analysis",
    ) -> ChangeImpactRecord:
        row = ChangeImpact(
            impact_id=impact_id,
            ecr_id=ecr_id,
            analysis_run_id=analysis_run_id,
            object_type="PART_REVISION",
            object_key=object_key,
            impact_type=impact_type,
            severity="INFO",
            reason=reason,
            evidence=evidence,
        )
        self._session.add(row)
        self._session.flush()
        return ChangeImpactRecord(
            row.impact_id, row.ecr_id, row.analysis_run_id, row.evidence
        )

    def get_change_impact(self, impact_id: uuid.UUID) -> ChangeImpactRecord | None:
        """Read a saved impact back through a stable record."""
        row = self._session.execute(
            select(ChangeImpact).where(ChangeImpact.impact_id == impact_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return ChangeImpactRecord(
            row.impact_id, row.ecr_id, row.analysis_run_id, row.evidence
        )

    def create_change_strategy(
        self,
        *,
        strategy_id: uuid.UUID,
        ecr_id: uuid.UUID,
        strategy_code: str,
        strategy_type: str,
        title: str,
        summary: str,
        effective_from: date,
        details: dict[str, Any],
        replacement_part_number: str | None = None,
        replacement_revision_code: str | None = None,
    ) -> ChangeStrategyRecord:
        row = ChangeStrategy(
            strategy_id=strategy_id,
            ecr_id=ecr_id,
            strategy_code=strategy_code,
            strategy_type=strategy_type,
            title=title,
            summary=summary,
            effective_from=effective_from,
            replacement_part_number=replacement_part_number,
            replacement_revision_code=replacement_revision_code,
            risk_level="UNASSESSED",
            cost_delta=Decimal(0),
            inventory_writeoff_cost=Decimal(0),
            currency="XXX",
            details=details,
            status="SELECTED",
        )
        self._session.add(row)
        self._session.flush()
        return ChangeStrategyRecord(
            row.strategy_id, row.ecr_id, row.strategy_code, row.status
        )

    def create_change_strategy_action(
        self,
        *,
        action_id: uuid.UUID,
        strategy_id: uuid.UUID,
        sequence_no: int,
        target_key: str,
        payload: dict[str, Any],
    ) -> ChangeStrategyActionRecord:
        row = ChangeStrategyAction(
            action_id=action_id,
            strategy_id=strategy_id,
            sequence_no=sequence_no,
            action_type="NOTIFY_OWNER",
            target_type="PART_REVISION",
            target_key=target_key,
            payload=payload,
            requires_approval=False,
        )
        self._session.add(row)
        self._session.flush()
        return ChangeStrategyActionRecord(
            row.action_id, row.strategy_id, row.sequence_no
        )

    def create_engineering_change_order(
        self,
        *,
        eco_id: uuid.UUID,
        eco_number: str,
        ecr_id: uuid.UUID,
        selected_strategy_id: uuid.UUID,
        effective_from: date,
    ) -> EngineeringChangeOrderRecord:
        row = EngineeringChangeOrder(
            eco_id=eco_id,
            eco_number=eco_number,
            ecr_id=ecr_id,
            selected_strategy_id=selected_strategy_id,
            status="DRAFT",
            effective_from=effective_from,
            approved_by=None,
            approved_at=None,
            executed_at=None,
        )
        self._session.add(row)
        self._session.flush()
        return EngineeringChangeOrderRecord(
            row.eco_id, row.ecr_id, row.selected_strategy_id, row.status
        )

    def create_execution_job(
        self,
        *,
        execution_job_id: uuid.UUID,
        eco_id: uuid.UUID,
        action_type: str = "APPLY_APPROVED_STRATEGY",
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> ExecutionJobRecord:
        row = ExecutionJob(
            execution_job_id=execution_job_id,
            eco_id=eco_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            payload=payload,
            status="PENDING",
            attempt_count=0,
            last_error=None,
            completed_at=None,
        )
        self._session.add(row)
        self._session.flush()
        return ExecutionJobRecord(row.execution_job_id, row.eco_id, row.status)
