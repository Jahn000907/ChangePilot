"""Supplier EOL workflow HTTP routes."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.runtime import (
    InvalidWorkflowApprovalError,
    SupplierEOLWorkflowRuntime,
    WorkflowThreadConflictError,
    WorkflowThreadNotFoundError,
)
from app.api.schemas import StartSupplierEOLWorkflowRequest
from app.domain.dto.approval import HumanApproval
from app.workflows.postgres_checkpoint import CHECKPOINT_CONNECTION_ERRORS
from app.workflows.state import SupplierEOLWorkflowExecutionResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/workflows/supplier-eol", tags=["supplier-eol"])


def get_workflow_runtime(request: Request) -> SupplierEOLWorkflowRuntime:
    """Return the application-scoped runtime shared across HTTP requests."""
    return request.app.state.workflow_runtime


@router.post("", response_model=SupplierEOLWorkflowExecutionResult)
def start_supplier_eol_workflow(
    payload: StartSupplierEOLWorkflowRequest,
    runtime: Annotated[SupplierEOLWorkflowRuntime, Depends(get_workflow_runtime)],
) -> SupplierEOLWorkflowExecutionResult:
    """Start a workflow and normally return its human-approval interrupt."""
    try:
        return runtime.start(payload)
    except WorkflowThreadConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CHECKPOINT_CONNECTION_ERRORS as exc:
        logger.exception("Supplier EOL checkpoint unavailable")
        raise HTTPException(status_code=503, detail="工作流状态存储暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("Supplier EOL workflow start failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="供应商停产分析执行失败",
        ) from exc


@router.get("/{thread_id}", response_model=SupplierEOLWorkflowExecutionResult)
def get_supplier_eol_workflow(
    thread_id: str,
    runtime: Annotated[SupplierEOLWorkflowRuntime, Depends(get_workflow_runtime)],
) -> SupplierEOLWorkflowExecutionResult:
    """Read the latest persisted checkpoint for an API-owned thread."""
    try:
        return runtime.get(thread_id)
    except WorkflowThreadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CHECKPOINT_CONNECTION_ERRORS as exc:
        logger.exception("Supplier EOL checkpoint lookup failed")
        raise HTTPException(status_code=503, detail="工作流状态存储暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("Supplier EOL workflow lookup failed")
        raise HTTPException(status_code=500, detail="工作流状态查询失败") from exc


@router.post(
    "/{thread_id}/approval",
    response_model=SupplierEOLWorkflowExecutionResult,
)
def approve_supplier_eol_workflow(
    thread_id: str,
    approval: HumanApproval,
    runtime: Annotated[SupplierEOLWorkflowRuntime, Depends(get_workflow_runtime)],
) -> SupplierEOLWorkflowExecutionResult:
    """Resume the pending LangGraph interrupt with a human decision."""
    try:
        return runtime.approve(thread_id, approval)
    except WorkflowThreadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidWorkflowApprovalError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WorkflowThreadConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CHECKPOINT_CONNECTION_ERRORS as exc:
        logger.exception("Supplier EOL checkpoint resume failed")
        raise HTTPException(status_code=503, detail="工作流状态存储暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("Supplier EOL workflow resume failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="供应商停产分析恢复失败",
        ) from exc
