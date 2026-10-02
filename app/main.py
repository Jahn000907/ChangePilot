"""Minimal FastAPI application entry point for ChangePilot."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.agent_runs import router as agent_runs_router
from app.api.routes.assistant import router as assistant_router
from app.api.routes.data import router as data_router
from app.api.routes.material_substitution import router as material_router
from app.api.routes.workflows import router as workflow_router
from app.api.runtime import MaterialSubstitutionRuntime, SupplierEOLWorkflowRuntime
from app.api.schemas import HealthResponse


def create_app(
    runtime: SupplierEOLWorkflowRuntime | None = None,
    material_runtime: MaterialSubstitutionRuntime | None = None,
) -> FastAPI:
    """Build an app with runtimes backed by shared PostgreSQL checkpoints."""
    application = FastAPI(title="ChangePilot", version="0.1.0")
    application.state.workflow_runtime = runtime or SupplierEOLWorkflowRuntime()
    application.state.material_substitution_runtime = material_runtime or MaterialSubstitutionRuntime()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    application.include_router(workflow_router)
    application.include_router(data_router)
    application.include_router(assistant_router)
    application.include_router(material_router)
    application.include_router(agent_runs_router)
    return application


app = create_app()
