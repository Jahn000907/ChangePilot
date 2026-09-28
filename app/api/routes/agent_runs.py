"""Read-only Agent run center endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.domain.dto.observability import AgentRunDetail, AgentRunSummary
from app.services.observability import ObservabilityService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agent-runs", tags=["agent-runs"])


def get_service() -> ObservabilityService:
    return ObservabilityService()


Service = Annotated[ObservabilityService, Depends(get_service)]


@router.get("", response_model=list[AgentRunSummary])
def recent_runs(
    service: Service, limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[AgentRunSummary]:
    try:
        return service.recent_runs(limit)
    except Exception as exc:
        logger.exception("Agent run list failed")
        raise HTTPException(status_code=500, detail="运行记录查询失败") from exc


@router.get("/{run_id}", response_model=AgentRunDetail)
def run_detail(run_id: uuid.UUID, service: Service) -> AgentRunDetail:
    try:
        return service.run_detail(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent run detail failed")
        raise HTTPException(status_code=500, detail="运行详情查询失败") from exc
