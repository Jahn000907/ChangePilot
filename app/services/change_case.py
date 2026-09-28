"""Minimal application service for persisting a Supplier EOL change case."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.postgres.repositories.ecm import ECMRepository
from app.db.postgres.session import create_session
from app.domain.dto.change_case import (
    SupplierEOLChangeCaseInput,
    SupplierEOLChangeCaseResult,
)
from app.domain.dto.eol_impact import SupplierEOLImpactResult
from app.domain.dto.material_substitution import (
    MaterialSubstitutionCaseResult,
    MaterialSubstitutionImpact,
    MaterialSubstitutionInput,
)
from app.domain.errors import EntityNotFoundError
from app.services.eol_impact import EOLImpactService
from app.services.material_substitution import MaterialSubstitutionService


class ChangeCaseService:
    """Create Case/ECR/Impact records around the existing EOL analysis."""

    def __init__(
        self,
        eol_impact: EOLImpactService | None = None,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._eol_impact = eol_impact if eol_impact is not None else EOLImpactService()
        self._session_factory = (
            session_factory if session_factory is not None else create_session
        )

    def create_supplier_eol_change_case(
        self, request: SupplierEOLChangeCaseInput
    ) -> SupplierEOLChangeCaseResult:
        """Persist the minimal Supplier EOL ECM chain in one transaction."""
        session = self._session_factory()
        try:
            repository = ECMRepository(session)
            case_id = uuid.uuid4()
            ecr_id = uuid.uuid4()
            analysis_run_id = uuid.uuid4()
            impact_id = uuid.uuid4()

            case = repository.create_change_case(
                case_id=case_id,
                case_number=request.case_number,
                raw_event=_event_payload(request),
                idempotency_key=request.idempotency_key,
                source_type=request.source_type,
                created_by=request.created_by,
            )
            ecr = repository.create_engineering_change_request(
                ecr_id=ecr_id,
                ecr_number=request.ecr_number,
                case_id=case.case_id,
                source_type=request.source_type,
                part_number=request.part_number,
                revision_code=request.revision_code,
                title=f"Supplier EOL: {request.part_number}/{request.revision_code}",
                description=(
                    f"{request.supplier_name} ({request.supplier_code}) will stop "
                    f"supplying {request.part_number}/{request.revision_code}; "
                    f"last-time-buy {request.last_time_buy_date.isoformat()}, "
                    f"EOL {request.eol_date.isoformat()}."
                ),
                priority=request.priority,
                requested_by=request.requested_by,
            )

            analysis = self._eol_impact.analyze_supplier_eol(
                part_number=request.part_number,
                revision_code=request.revision_code,
                as_of_date=request.as_of_date,
            )
            repository.create_change_impact(
                impact_id=impact_id,
                ecr_id=ecr.ecr_id,
                analysis_run_id=analysis_run_id,
                object_key=f"{request.part_number}|{request.revision_code}",
                evidence=analysis.model_dump(mode="json"),
            )
            saved_impact = repository.get_change_impact(impact_id)
            if saved_impact is None:
                raise EntityNotFoundError(
                    f"change impact was not readable after insert: {impact_id}"
                )
            persisted_analysis = SupplierEOLImpactResult.model_validate(
                saved_impact.evidence
            )
            session.commit()
            return SupplierEOLChangeCaseResult(
                case_id=case.case_id,
                case_number=case.case_number,
                case_status=case.status,
                ecr_id=ecr.ecr_id,
                ecr_number=ecr.ecr_number,
                ecr_status=ecr.status,
                impact_id=saved_impact.impact_id,
                analysis_run_id=saved_impact.analysis_run_id,
                impact=persisted_analysis,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_material_substitution_change_case(
        self, request: MaterialSubstitutionInput, *, thread_id: str
    ) -> MaterialSubstitutionCaseResult:
        """Persist one substitution Case/ECR/Impact using the existing ECM tables."""
        session = self._session_factory()
        try:
            repository = ECMRepository(session)
            case_id, ecr_id, impact_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            suffix = case_id.hex[:12].upper()
            # Deterministic facts are gathered before the single ECM commit.
            impact = MaterialSubstitutionService().analyze(request)
            case = repository.create_change_case(
                case_id=case_id, case_number=f"CASE-SUB-{suffix}",
                raw_event=request.model_dump(mode="json"),
                idempotency_key=f"material-substitution:{thread_id}",
                source_type="EMPLOYEE_REQUEST", created_by=request.requested_by,
                case_type="MATERIAL_SUBSTITUTION",
            )
            ecr = repository.create_engineering_change_request(
                ecr_id=ecr_id, ecr_number=f"ECR-SUB-{suffix}", case_id=case.case_id,
                source_type="EMPLOYEE_REQUEST", part_number=request.part_number,
                revision_code=request.revision_code,
                title=f"物料替代评估：{request.part_number} → {request.candidate_part_number}",
                description=(f"评估 {request.part_number}/{request.revision_code} 替换为 "
                             f"{impact.candidate_part_number}/{impact.candidate_revision_code}"),
                priority=request.priority, requested_by=request.requested_by,
                change_type="MATERIAL_SUBSTITUTION",
            )
            saved = repository.create_change_impact(
                impact_id=impact_id, ecr_id=ecr.ecr_id,
                analysis_run_id=uuid.uuid4(),
                object_key=f"{request.part_number}|{request.revision_code}",
                evidence=impact.model_dump(mode="json"),
                impact_type="MATERIAL_SUBSTITUTION_ANALYSIS",
                reason="Deterministic material substitution impact analysis",
            )
            reread = repository.get_change_impact(saved.impact_id)
            if reread is None:
                raise EntityNotFoundError("替代评估结果写入后无法读取")
            session.commit()
            return MaterialSubstitutionCaseResult(
                case_id=case.case_id, case_number=case.case_number,
                ecr_id=ecr.ecr_id, ecr_number=ecr.ecr_number,
                impact_id=saved.impact_id,
                impact=MaterialSubstitutionImpact.model_validate(reread.evidence),
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _event_payload(request: SupplierEOLChangeCaseInput) -> dict[str, object]:
    """Return only the external Supplier EOL event facts for ``raw_event``."""
    return {
        "source_type": request.source_type,
        "supplier_code": request.supplier_code,
        "supplier_name": request.supplier_name,
        "part_number": request.part_number,
        "revision_code": request.revision_code,
        "last_time_buy_date": request.last_time_buy_date.isoformat(),
        "eol_date": request.eol_date.isoformat(),
    }
