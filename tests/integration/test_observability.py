"""Safe presentation boundaries for the read-only run center."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.observability import ObservabilityService


def test_unknown_run_is_not_found() -> None:
    client = TestClient(create_app())
    assert client.get(f"/api/v1/agent-runs/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/v1/agent-runs?limit=0").status_code == 422


def test_tool_view_redacts_secrets_and_raw_result() -> None:
    row = SimpleNamespace(
        tool_call_id=uuid.uuid4(), step_id=uuid.uuid4(),
        tool_name="get_inventory", agent_name="SupplyAgent", status="SUCCEEDED",
        latency_ms=235, created_at=datetime.now(UTC),
        arguments={"part_number": "BRG-6204-A", "api_key": "secret-value",
                   "password": "private-password", "revision_code": "A"},
        result_summary={"content_preview": '{"rows":[{"qty_on_hand":"700",'
                                                 '"api_key":"secret-value"}]}'},
    )
    view = ObservabilityService._call(row)
    serialized = view.model_dump_json()
    assert view.arguments == {"part_number": "BRG-6204-A", "revision_code": "A"}
    assert view.result_summary == "返回 1 项rows结果。"
    assert "secret-value" not in serialized
    assert "private-password" not in serialized
    assert "700" not in serialized


def test_duration_has_business_precision() -> None:
    now = datetime.now(UTC)
    assert ObservabilityService._duration(now, None, 235) == 235
