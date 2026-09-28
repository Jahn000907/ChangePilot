"""Workflow API lifecycle backed by durable LangGraph checkpoints."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import nullcontext

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver

from app.agents.review import ReviewAgent
from app.agents.strategy import StrategyAgent
from app.api.schemas import StartSupplierEOLWorkflowRequest
from app.domain.dto.approval import HumanApproval
from app.domain.dto.change_case import SupplierEOLChangeCaseInput
from app.domain.dto.material_substitution import (
    MaterialSubstitutionInput,
    MaterialSubstitutionWorkflowResult,
)
from app.workflows.material_substitution import (
    get_material_substitution_workflow_result,
    resume_material_substitution_workflow,
    run_material_substitution_workflow,
)
from app.workflows.postgres_checkpoint import (
    MATERIAL_SUBSTITUTION_NAMESPACE,
    SUPPLIER_EOL_NAMESPACE,
    get_postgres_checkpointer,
    workflow_thread_lock,
)
from app.workflows.state import SupplierEOLWorkflowExecutionResult
from app.workflows.supplier_eol import (
    get_supplier_eol_workflow_result,
    resume_supplier_eol_workflow,
    run_supplier_eol_workflow,
)


class WorkflowThreadNotFoundError(LookupError):
    """The requested API-owned workflow thread does not exist."""


class WorkflowThreadConflictError(RuntimeError):
    """The requested operation conflicts with the thread's current state."""


class InvalidWorkflowApprovalError(ValueError):
    """Approval is valid structurally but invalid for the pending workflow."""


class SupplierEOLWorkflowRuntime:
    """Read each public result from PostgreSQL, including after process restart."""

    def __init__(
        self,
        *,
        checkpointer: BaseCheckpointSaver | None = None,
        strategy_agent_factory: Callable[[], StrategyAgent] | None = None,
        review_agent_factory: Callable[[], ReviewAgent] | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._strategy_agent_factory = strategy_agent_factory
        self._review_agent_factory = review_agent_factory

    @property
    def checkpointer(self) -> BaseCheckpointSaver:
        if self._checkpointer is None:
            self._checkpointer = get_postgres_checkpointer()
        return self._checkpointer

    def start(
        self,
        request: StartSupplierEOLWorkflowRequest,
    ) -> SupplierEOLWorkflowExecutionResult:
        saver = self.checkpointer
        guard = workflow_thread_lock(SUPPLIER_EOL_NAMESPACE, request.thread_id) if isinstance(saver, PostgresSaver) else nullcontext()
        with guard:
            try:
                self.get(request.thread_id)
            except WorkflowThreadNotFoundError:
                pass
            else:
                raise WorkflowThreadConflictError("工作流线程已存在")
            suffix = uuid.uuid4().hex[:12]
            workflow_input = SupplierEOLChangeCaseInput(
                case_number=f"CASE-API-{suffix}",
                ecr_number=f"ECR-API-{suffix}",
                idempotency_key=f"api:supplier-eol:{request.thread_id}",
                supplier_code=request.supplier_code,
                supplier_name=request.supplier_name,
                part_number=request.part_number,
                revision_code=request.revision,
                last_time_buy_date=request.last_time_buy_date,
                eol_date=request.eol_date,
                as_of_date=request.as_of_date,
                priority=request.priority,
                requested_by=request.requested_by,
                created_by=request.requested_by,
                source_type=request.source_type,
            )
            return run_supplier_eol_workflow(
                workflow_input,
                thread_id=request.thread_id,
                strategy_agent=(
                    self._strategy_agent_factory()
                    if self._strategy_agent_factory is not None else None
                ),
                review_agent=(
                    self._review_agent_factory()
                    if self._review_agent_factory is not None else None
                ),
                checkpointer=saver,
            )

    def get(self, thread_id: str) -> SupplierEOLWorkflowExecutionResult:
        try:
            return get_supplier_eol_workflow_result(thread_id, checkpointer=self.checkpointer)
        except LookupError as exc:
            raise WorkflowThreadNotFoundError("工作流 Checkpoint 不存在") from exc

    def approve(
        self,
        thread_id: str,
        approval: HumanApproval,
    ) -> SupplierEOLWorkflowExecutionResult:
        saver = self.checkpointer
        guard = workflow_thread_lock(SUPPLIER_EOL_NAMESPACE, thread_id) if isinstance(saver, PostgresSaver) else nullcontext()
        with guard:
            current = self.get(thread_id)
            if current.status != "INTERRUPTED":
                raise WorkflowThreadConflictError("工作流已完成或当前不在人工审批节点")
            if (approval.decision == "APPROVE"
                    and approval.selected_strategy_index >= len(current.state.strategies)):
                raise InvalidWorkflowApprovalError("所选策略超出候选范围")
            return resume_supplier_eol_workflow(
                thread_id=thread_id, approval=approval, checkpointer=saver,
            )


class MaterialSubstitutionRuntime:
    """Reconstruct the second formal workflow from persistent checkpoints."""

    def __init__(
        self, *, checkpointer: BaseCheckpointSaver | None = None,
        strategy_agent_factory: Callable[[], StrategyAgent] | None = None,
        review_agent_factory: Callable[[], ReviewAgent] | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._strategy_factory = strategy_agent_factory
        self._review_factory = review_agent_factory

    @property
    def checkpointer(self) -> BaseCheckpointSaver:
        if self._checkpointer is None:
            self._checkpointer = get_postgres_checkpointer()
        return self._checkpointer

    def start(
        self, *, thread_id: str, event: MaterialSubstitutionInput
    ) -> MaterialSubstitutionWorkflowResult:
        saver = self.checkpointer
        guard = workflow_thread_lock(MATERIAL_SUBSTITUTION_NAMESPACE, thread_id) if isinstance(saver, PostgresSaver) else nullcontext()
        with guard:
            try:
                self.get(thread_id)
            except WorkflowThreadNotFoundError:
                pass
            else:
                raise WorkflowThreadConflictError("工作流线程已存在")
            return run_material_substitution_workflow(
                event, thread_id=thread_id, checkpointer=saver,
                strategy_agent=self._strategy_factory() if self._strategy_factory else None,
                review_agent=self._review_factory() if self._review_factory else None,
            )

    def get(self, thread_id: str) -> MaterialSubstitutionWorkflowResult:
        try:
            return get_material_substitution_workflow_result(
                thread_id, checkpointer=self.checkpointer,
            )
        except LookupError as exc:
            raise WorkflowThreadNotFoundError("工作流 Checkpoint 不存在") from exc

    def approve(
        self, thread_id: str, approval: HumanApproval
    ) -> MaterialSubstitutionWorkflowResult:
        saver = self.checkpointer
        guard = workflow_thread_lock(MATERIAL_SUBSTITUTION_NAMESPACE, thread_id) if isinstance(saver, PostgresSaver) else nullcontext()
        with guard:
            current = self.get(thread_id)
            if current.status != "INTERRUPTED":
                raise WorkflowThreadConflictError("工作流已完成或当前不在人工审批节点")
            if approval.selected_strategy_index >= len(current.state.strategies):
                raise InvalidWorkflowApprovalError("所选策略超出候选范围")
            return resume_material_substitution_workflow(
                thread_id=thread_id, approval=approval, checkpointer=saver,
            )
