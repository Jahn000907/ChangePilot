"""Integration test for the minimal Supplier EOL ECM persistence chain."""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
from neo4j.exceptions import Neo4jError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.neo4j.driver import close_driver, get_driver
from app.db.postgres.models.ecm import (
    ChangeCase,
    ChangeImpact,
    EngineeringChangeRequest,
)
from app.db.postgres.session import create_session
from app.domain.dto.change_case import SupplierEOLChangeCaseInput
from app.domain.errors import EntityNotFoundError
from app.services.change_case import ChangeCaseService


def test_supplier_eol_change_case_persists_and_reads_back():
    """Case, ECR and serialized impact are committed with correct links."""
    try:
        get_driver().verify_connectivity()
    except (Neo4jError, OSError) as exc:  # pragma: no cover - environment
        pytest.skip(f"Neo4j is not reachable: {exc}")
    try:
        with create_session() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:  # pragma: no cover - environment
        close_driver()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    suffix = uuid.uuid4().hex[:12]
    result = None
    try:
        request = SupplierEOLChangeCaseInput(
            case_number=f"CASE-T-{suffix}",
            ecr_number=f"ECR-T-{suffix}",
            idempotency_key=f"test:supplier-eol:{suffix}",
            supplier_code="SUP-001",
            supplier_name="MotionWorks",
            part_number="BRG-6204-A",
            revision_code="A",
            last_time_buy_date=date(2026, 11, 30),
            eol_date=date(2027, 1, 31),
            as_of_date=date(2026, 9, 20),
            requested_by="integration-test",
            created_by="integration-test",
        )
        try:
            result = ChangeCaseService().create_supplier_eol_change_case(request)
        except EntityNotFoundError as exc:  # pragma: no cover - seed dependent
            pytest.skip(f"golden seed is not loaded: {exc}")

        with create_session() as session:
            case = session.get(ChangeCase, result.case_id)
            ecr = session.get(EngineeringChangeRequest, result.ecr_id)
            impact = session.get(ChangeImpact, result.impact_id)

            assert case is not None
            assert ecr is not None and ecr.case_id == case.case_id
            assert impact is not None and impact.ecr_id == ecr.ecr_id
            assert impact.analysis_run_id == result.analysis_run_id
            assert impact.evidence["part_number"] == "BRG-6204-A"
            reread_evidence = session.execute(
                select(ChangeImpact.evidence).where(
                    ChangeImpact.impact_id == result.impact_id
                )
            ).scalar_one()
            assert reread_evidence == impact.evidence

        payload = json.loads(result.model_dump_json())
        assert payload["impact"]["part_number"] == "BRG-6204-A"
        assert payload["case_status"] == "PLANNING"
        assert payload["ecr_status"] == "PLANNING"
    finally:
        close_driver()
        if result is not None:
            with create_session() as session:
                session.execute(
                    delete(ChangeImpact).where(ChangeImpact.impact_id == result.impact_id)
                )
                session.execute(
                    delete(EngineeringChangeRequest).where(
                        EngineeringChangeRequest.ecr_id == result.ecr_id
                    )
                )
                session.execute(
                    delete(ChangeCase).where(ChangeCase.case_id == result.case_id)
                )
                session.commit()
