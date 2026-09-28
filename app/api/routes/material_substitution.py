"""HTTP entry points for the formal material-substitution workflow."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from app.api.runtime import (
    InvalidWorkflowApprovalError,
    MaterialSubstitutionRuntime,
    WorkflowThreadConflictError,
    WorkflowThreadNotFoundError,
)
from app.domain.dto.approval import HumanApproval
from app.domain.dto.material_substitution import (
    MaterialSubstitutionInput,
    MaterialSubstitutionWorkflowResult,
)
from app.workflows.postgres_checkpoint import CHECKPOINT_CONNECTION_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/workflows/material-substitution", tags=["material-substitution"])


class StartMaterialSubstitutionRequest(MaterialSubstitutionInput):
    thread_id: str = Field(min_length=1, max_length=64)


def get_runtime(request: Request) -> MaterialSubstitutionRuntime:
    return request.app.state.material_substitution_runtime


Runtime = Annotated[MaterialSubstitutionRuntime, Depends(get_runtime)]


@router.post("", response_model=MaterialSubstitutionWorkflowResult)
def start(request: StartMaterialSubstitutionRequest, runtime: Runtime) -> MaterialSubstitutionWorkflowResult:
    try:
        event = MaterialSubstitutionInput.model_validate(request.model_dump(exclude={"thread_id"}))
        return runtime.start(thread_id=request.thread_id, event=event)
    except WorkflowThreadConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CHECKPOINT_CONNECTION_ERRORS as exc:
        logger.exception("Material substitution checkpoint unavailable")
        raise HTTPException(status_code=503, detail="工作流状态存储暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("Material substitution workflow start failed")
        raise HTTPException(status_code=500, detail="物料替代评估执行失败") from exc


@router.get("/{thread_id}", response_model=MaterialSubstitutionWorkflowResult)
def get(thread_id: str, runtime: Runtime) -> MaterialSubstitutionWorkflowResult:
    try:
        return runtime.get(thread_id)
    except WorkflowThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CHECKPOINT_CONNECTION_ERRORS as exc:
        logger.exception("Material substitution checkpoint lookup failed")
        raise HTTPException(status_code=503, detail="工作流状态存储暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("Material substitution workflow lookup failed")
        raise HTTPException(status_code=500, detail="工作流状态查询失败") from exc


@router.post("/{thread_id}/approval", response_model=MaterialSubstitutionWorkflowResult)
def approve(
    thread_id: str, approval: HumanApproval, runtime: Runtime
) -> MaterialSubstitutionWorkflowResult:
    try:
        return runtime.approve(thread_id, approval)
    except WorkflowThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidWorkflowApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkflowThreadConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CHECKPOINT_CONNECTION_ERRORS as exc:
        logger.exception("Material substitution checkpoint resume failed")
        raise HTTPException(status_code=503, detail="工作流状态存储暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("Material substitution workflow resume failed")
        raise HTTPException(status_code=500, detail="物料替代评估恢复失败") from exc
