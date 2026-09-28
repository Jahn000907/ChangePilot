"""Atomic creation of records for one approved engineering strategy."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.db.postgres.repositories.ecm import ECMRepository
from app.db.postgres.session import create_session
from app.domain.dto.approval import HumanApproval
from app.domain.dto.change_case import SupplierEOLChangeCaseInput
from app.domain.dto.execution import ExecutionResult
from app.domain.dto.material_substitution import MaterialSubstitutionInput
from app.domain.dto.strategy import StrategyCandidate, StrategyType

_PERSISTED_STRATEGY_TYPES: dict[StrategyType, str] = {
    StrategyType.LAST_TIME_BUY: "LAST_TIME_BUY",
    StrategyType.QUALIFIED_ALTERNATIVE: "IMMEDIATE_REPLACEMENT",
    StrategyType.QUALIFICATION_REQUIRED: "SPLIT_EFFECTIVITY",
    StrategyType.REDESIGN: "IMMEDIATE_REPLACEMENT",
    StrategyType.SUPPLY_MITIGATION: "INVENTORY_RUN_OUT",
}


class ExecutionService:
    """Persist Strategy, Actions, ECO and Execution Job in one transaction."""

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._session_factory = session_factory or create_session

    def execute_approved_strategy(
        self,
        *,
        ecr_id: uuid.UUID,
        event: SupplierEOLChangeCaseInput,
        strategy: StrategyCandidate,
        approval: HumanApproval,
    ) -> ExecutionResult:
        """Create the minimal downstream execution records atomically."""
        return self._execute(
            ecr_id=ecr_id, part_number=event.part_number,
            revision_code=event.revision_code, effective_from=event.eol_date,
            strategy=strategy, approval=approval, scenario="SUPPLIER_EOL",
            priority=event.priority, supplier_code=event.supplier_code,
        )

    def execute_approved_substitution(
        self, *, ecr_id: uuid.UUID, event: MaterialSubstitutionInput,
        candidate_revision_code: str, strategy: StrategyCandidate, approval: HumanApproval,
    ) -> ExecutionResult:
        return self._execute(
            ecr_id=ecr_id, part_number=event.part_number,
            revision_code=event.revision_code, effective_from=event.as_of_date,
            strategy=strategy, approval=approval,
            scenario="MATERIAL_SUBSTITUTION", priority=event.priority,
            replacement_part_number=event.candidate_part_number,
            replacement_revision_code=candidate_revision_code,
        )

    def _execute(
        self, *, ecr_id: uuid.UUID, part_number: str, revision_code: str,
        effective_from: date, strategy: StrategyCandidate, approval: HumanApproval,
        replacement_part_number: str | None = None,
        replacement_revision_code: str | None = None,
        scenario: str = "SUPPLIER_EOL", priority: str = "HIGH",
        supplier_code: str | None = None,
    ) -> ExecutionResult:
        session = self._session_factory()
        try:
            repository = ECMRepository(session)
            existing = repository.get_execution_for_ecr(ecr_id)
            if existing is not None:
                return ExecutionResult(
                    strategy_id=existing[0], eco_id=existing[1],
                    execution_job_ids=existing[2], status="PENDING",
                    summary="已存在执行记录，复用原 Strategy、ECO 与 Execution Job。",
                )
            strategy_id = uuid.uuid4()
            eco_id = uuid.uuid4()
            strategy_code = f"STR-{strategy_id.hex[:12].upper()}"
            eco_number = f"ECO-{eco_id.hex[:12].upper()}"
            target_key = f"{part_number}/{revision_code}"
            case_id = repository.case_id_for_ecr(ecr_id)

            persisted_strategy = repository.create_change_strategy(
                strategy_id=strategy_id,
                ecr_id=ecr_id,
                strategy_code=strategy_code,
                strategy_type=_PERSISTED_STRATEGY_TYPES[strategy.strategy_type],
                title=strategy.title,
                summary=strategy.summary,
                effective_from=effective_from,
                replacement_part_number=replacement_part_number,
                replacement_revision_code=replacement_revision_code,
                details={
                    "source_strategy_type": strategy.strategy_type.value,
                    "rationale": strategy.rationale,
                    "risks": strategy.risks,
                    "approval_comment": approval.comment,
                    "approved_by": approval.reviewer,
                    "financial_estimates_available": False,
                    **({
                        "candidate_part_number": replacement_part_number,
                        "candidate_revision_code": replacement_revision_code,
                    } if replacement_part_number is not None else {}),
                },
            )
            for sequence_no, action in enumerate(strategy.actions, start=1):
                repository.create_change_strategy_action(
                    action_id=uuid.uuid4(),
                    strategy_id=persisted_strategy.strategy_id,
                    sequence_no=sequence_no,
                    target_key=target_key,
                    payload={
                        "description": action,
                        "source_strategy_type": strategy.strategy_type.value,
                    },
                )

            eco = repository.create_engineering_change_order(
                eco_id=eco_id,
                eco_number=eco_number,
                ecr_id=ecr_id,
                selected_strategy_id=persisted_strategy.strategy_id,
                effective_from=effective_from,
            )
            job_ids: list[uuid.UUID] = []
            for action_type, title, description, department in self._job_plan(scenario):
                job = repository.create_execution_job(
                    execution_job_id=uuid.uuid4(), eco_id=eco.eco_id,
                    action_type=action_type,
                    idempotency_key=f"execution:{ecr_id}:{action_type}",
                    payload={
                        "title": title, "description": description,
                        "owner_department": department, "priority": priority,
                        "case_id": str(case_id), "ecr_id": str(ecr_id),
                        "eco_id": str(eco.eco_id), "strategy_id": str(strategy_id),
                        "strategy_code": strategy_code,
                        "strategy_type": strategy.strategy_type.value,
                        "part_number": part_number, "revision_code": revision_code,
                        "candidate_part_number": replacement_part_number,
                        "candidate_revision_code": replacement_revision_code,
                        "supplier_code": supplier_code,
                        "target_key": target_key,
                        "approved_actions": strategy.actions,
                        "execution_mode": "CONTROLLED_RECORD_ONLY",
                    },
                )
                job_ids.append(job.execution_job_id)
            session.commit()
            return ExecutionResult(
                strategy_id=persisted_strategy.strategy_id,
                eco_id=eco.eco_id,
                execution_job_ids=job_ids,
                status="PENDING",
                summary=f"已创建策略 {strategy_code}、ECO {eco_number} 和 {len(job_ids)} 项受控执行任务。",
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _job_plan(scenario: str) -> tuple[tuple[str, str, str, str], ...]:
        if scenario == "MATERIAL_SUBSTITUTION":
            return (
                ("SUBSTITUTION_VALIDATION", "核验替代料资格与工程验证",
                 "复核候选料资格、验证记录及适用范围；未完成验证前不得直接切换。", "工程质量"),
                ("PRODUCTION_ACTION", "核对生产切换计划",
                 "核对相关生产需求与物料切换时点，形成待审批的生产调整方案。", "生产计划"),
                ("PURCHASE_ACTION", "核对替代料采购安排",
                 "复核原料与候选料采购安排；本任务不修改采购订单。", "采购"),
                ("BOM_REDLINE_DRAFT", "准备 BOM Redline 草案",
                 "确认源 BOM 版本与行项目后准备草案；当前未修改 BOM 或创建 Redline。", "产品工程"),
            )
        return (
            ("SUPPLIER_COMMUNICATION", "确认停产通知与最后采购窗口",
             "与供应商核对停产时间、最后采购日及交付承诺。", "采购"),
            ("PURCHASE_ACTION", "核对最后采购与未完成订单",
             "按已批准策略核对采购需求与未完成订单；本任务不修改采购订单。", "采购"),
            ("PRODUCTION_ACTION", "核对受影响生产计划",
             "核对冻结需求和生产安排，准备受控调整方案。", "生产计划"),
            ("DELIVERY_REVIEW", "复核客户交付影响",
             "核对相关销售订单和交付承诺；未核验前不认定具体订单受影响。", "销售运营"),
        )
