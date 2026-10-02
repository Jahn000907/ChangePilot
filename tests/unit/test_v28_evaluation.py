"""Deterministic V2.8 benchmark and optional tracing boundaries."""

from __future__ import annotations

import json

from app.agents.enterprise_assistant import AssistantAnswer, ToolFact
from app.domain.dto.assistant import AssistantContext
from app.llm import tracing
from evals.assistant_metrics import AssistantBenchmarkCase, evaluate_case, load_cases
from evals.judge import judge_answer
from evals.run import run_benchmark


def _case(**overrides: object) -> AssistantBenchmarkCase:
    data: dict[str, object] = {
        "case_id": "x", "category": "single_tool", "question": "PART-X 库存多少？",
        "expected_tools": ["get_inventory"], "expected_agents": [],
        "should_use_supervisor": False, "expected_workflow_suggestion": None,
    }
    data.update(overrides)
    return AssistantBenchmarkCase.model_validate(data)


def _answer(text: str = "PART-X 库存 7") -> AssistantAnswer:
    return AssistantAnswer(
        text=text, tool_names=["get_inventory"], context=AssistantContext(),
        facts=[ToolFact("get_inventory", {"part_number": "PART-X"}, {"qty_on_hand": 7})],
    )


def test_dataset_is_fixed_and_unique() -> None:
    cases = load_cases()
    assert len(cases) >= 10
    assert len({item.case_id for item in cases}) == len(cases)
    assert {"general", "single_tool", "multi_agent", "suggestion", "no_data"} <= {
        item.category for item in cases
    }
    by_id = {item.case_id: item for item in cases}
    assert "get_supplier_parts" in by_id["supply_risk"].allowed_tools
    assert "get_sales_orders_for_products" in by_id["eol_impact"].expected_tools
    assert "get_sales_order_records" in by_id["eol_impact"].forbidden_tools
    assert by_id["no_data"].question.startswith("PART-NOT-EXIST")
    assert by_id["no_data"].expected_tools == ["get_inventory"]


def test_selection_supervisor_grounding_and_suggestion_metrics() -> None:
    case = _case(expected_agents=["SupplyAgent"], should_use_supervisor=True)
    result = evaluate_case(
        case, _answer("PART-X 库存 7，PO-FAKE-999 订购 99999"),
        actual_tools=["get_inventory"], actual_agents=["SupplyAgent", "DeliveryAgent"],
        used_supervisor=True, suggestion=None, latency_ms=12,
    )
    assert result.metrics["tool_selection_accuracy"] == 1
    assert result.metrics["agent_selection_precision"] == 0.5
    assert result.metrics["agent_selection_recall"] == 1
    assert result.metrics["agent_selection_exact"] == 0
    assert result.metrics["supervisor_routing_accuracy"] == 1
    assert result.metrics["fact_grounding_rate"] < 1
    assert result.metrics["unsupported_fact_rate"] > 0
    assert "PO-FAKE-999" in " ".join(result.issues)
    assert evaluate_case(
        _case(expected_workflow_suggestion="supplier_eol"), _answer(),
        actual_tools=[], actual_agents=[], used_supervisor=False,
        suggestion=None, latency_ms=1,
    ).metrics["workflow_suggestion_accuracy"] == 0


def test_expected_fact_must_match_same_record() -> None:
    case = _case(expected_tools=["get_alternatives"], expected_facts={"BRG-6204-B": "QUALIFIED"})
    answer = AssistantAnswer(
        text="候选料待核验。", tool_names=["get_alternatives"], context=AssistantContext(),
        facts=[ToolFact("get_alternatives", {}, {"rows": [
            {"alternative_part_number": "BRG-6204-B", "qualification_status": "UNQUALIFIED"},
            {"alternative_part_number": "BRG-6204-C", "qualification_status": "QUALIFIED"},
        ]})],
    )
    result = evaluate_case(
        case, answer, actual_tools=["get_alternatives"], actual_agents=[],
        used_supervisor=False, suggestion=None, latency_ms=1,
    )
    assert result.metrics["task_completion_rate"] == 0
    assert "缺少期望事实" in " ".join(result.issues)


def test_optional_supplier_evidence_is_not_a_tool_selection_failure() -> None:
    case = _case(
        category="multi_agent", expected_tools=["get_inventory", "get_purchase_orders"],
        allowed_tools=["get_supplier_parts"], expected_agents=["SupplyAgent"],
        allowed_agents=["StructureAgent"], should_use_supervisor=True,
    )
    answer = AssistantAnswer("已核验供应关系。", [], AssistantContext(), [])
    result = evaluate_case(
        case, answer, actual_tools=["get_inventory", "get_purchase_orders", "get_supplier_parts"],
        actual_agents=["SupplyAgent"], used_supervisor=True, suggestion=None, latency_ms=1,
    )
    assert result.passed
    assert result.metrics["tool_selection_accuracy"] == 1


def test_deterministic_row_derivations_are_grounded_but_fabricated_value_is_not() -> None:
    facts = [
        ToolFact("get_purchase_orders", {}, {"rows": [
            {"ordered_qty": "500", "received_qty": "0"},
            {"ordered_qty": "300", "received_qty": "100"},
            {"ordered_qty": "200", "received_qty": "0"},
        ]}),
        ToolFact("get_production_requirements", {}, {"rows": [
            *[{"order_number": f"MO-{index}", "order_status": "RELEASED", "required_qty": qty}
              for index, qty in enumerate([50, 40, 35, 35, 35, 35, 35, 30, 27], start=1)],
            {"order_number": "MO-10", "order_status": "COMPLETED", "required_qty": 10},
            {"order_number": "MO-11", "order_status": "CANCELLED", "required_qty": 20},
        ]}),
    ]
    answer = AssistantAnswer(
        "订购 1000，已收 100，未收 900；11 条需求中有 9 个活动订单，有效需求 322。",
        [], AssistantContext(), facts,
    )
    result = evaluate_case(
        _case(category="multi_agent", expected_tools=["get_purchase_orders", "get_production_requirements"]),
        answer, actual_tools=["get_purchase_orders", "get_production_requirements"],
        actual_agents=[], used_supervisor=False, suggestion=None, latency_ms=1,
    )
    assert {"1000", "900", "9", "322"} <= set(result.derived_grounded_facts)
    assert not result.unsupported_facts
    fabricated = evaluate_case(
        _case(expected_tools=["get_purchase_orders"]),
        AssistantAnswer("未收 901。", [], AssistantContext(), facts[:1]),
        actual_tools=["get_purchase_orders"], actual_agents=[], used_supervisor=False,
        suggestion=None, latency_ms=1,
    )
    assert "901" in fabricated.unsupported_facts


def test_general_answer_needs_no_tool_and_benchmark_writes_reports(tmp_path) -> None:
    case = _case(category="general", expected_tools=[], question="什么是 BOM？")
    answer = AssistantAnswer("BOM 是物料清单。", [], AssistantContext(), [])
    result = evaluate_case(
        case, answer, actual_tools=[], actual_agents=[], used_supervisor=False,
        suggestion=None, latency_ms=1,
    )
    assert result.passed
    assert result.metrics["fact_grounding_rate"] == 1
    terminology = evaluate_case(
        case, AssistantAnswer("BOM 与 Where-Used 是不同的结构查询。", [], AssistantContext(), []),
        actual_tools=[], actual_agents=[], used_supervisor=False,
        suggestion=None, latency_ms=1,
    )
    assert terminology.metrics["unsupported_fact_rate"] == 0
    fabricated = evaluate_case(
        case, AssistantAnswer("BRG-6204-A 库存 820。", [], AssistantContext(), []),
        actual_tools=[], actual_agents=[], used_supervisor=False,
        suggestion=None, latency_ms=1,
    )
    assert fabricated.metrics["unsupported_fact_rate"] > 0
    report = run_benchmark(limit=2, output_dir=tmp_path)
    assert report["case_count"] == 2
    assert (tmp_path / "assistant_v28.md").exists()
    assert json.loads((tmp_path / "assistant_v28.json").read_text(encoding="utf-8"))["cases"]


def test_langsmith_disabled_does_not_wrap_client(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    tracing._settings.cache_clear()
    tracing._client.cache_clear()
    marker = object()
    try:
        assert tracing.instrument_openai(marker) is marker
        with tracing.trace_scope("disabled"):
            pass
    finally:
        tracing._settings.cache_clear()
        tracing._client.cache_clear()


def test_langsmith_enabled_wraps_existing_client_without_replacing_settings(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-only-key")
    tracing._settings.cache_clear()
    tracing._client.cache_clear()
    seen = []
    monkeypatch.setattr(tracing, "wrap_openai", lambda client: seen.append(client) or client)
    marker = object()
    try:
        assert tracing.instrument_openai(marker) is marker
        assert seen == [marker]
    finally:
        tracing._settings.cache_clear()
        tracing._client.cache_clear()


def test_default_fake_benchmark_never_traces_even_when_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tracing, "trace", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("default benchmark attempted upload"),
    ))
    assert run_benchmark(limit=1, output_dir=tmp_path)["passed"] == 1


def test_optional_judge_is_structured_and_isolated_from_fact_metrics() -> None:
    class FakeJudge:
        def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
            assert "不判断库存数值" in system_prompt
            assert "evidence" in user_prompt
            return '{"grounded_analysis":0.8,"completeness":0.7,"clarity":1,"comment":"清晰"}'

    result = judge_answer(FakeJudge(), question="分析", answer="回答", evidence="事实")
    assert result.clarity == 1
