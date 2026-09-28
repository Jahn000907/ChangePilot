"""Run the V2.8 fixed Assistant benchmark without cloud calls by default."""

from __future__ import annotations

import argparse
import json
import subprocess
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import delete, select

from app.agents.enterprise_assistant import AssistantAnswer, EnterpriseAssistant
from app.db.postgres.models.agent import AgentRun, AgentStep, ToolCall
from app.db.postgres.session import create_session
from app.domain.dto.assistant import AssistantContext
from app.llm.client import DeepSeekLLMClient
from app.llm.tracing import langsmith_project, without_tracing
from app.services.assistant import AssistantService
from app.services.trace import TraceService
from app.tools.langchain import get_enterprise_tools
from app.tools.schemas import GetInventoryInput
from evals.assistant_metrics import CaseEvaluation, evaluate_case, load_cases


class FakeAssistantLLM:
    """Controlled orchestration responses; enterprise facts still come from real Tools."""

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        if "跨域/综合" in system_prompt:
            question = json.loads(user_prompt)["question"]
            if "综合分析" in question:
                selected = [
                    ("StructureAgent", ["find_where_used", "get_alternatives"]),
                    ("SupplyAgent", ["get_inventory", "get_purchase_orders"]),
                    ("ProductionAgent", ["get_production_requirements"]),
                    ("DeliveryAgent", ["get_sales_order_records"]),
                ]
            elif "供应风险" in question:
                selected = [
                    ("SupplyAgent", ["get_inventory", "get_purchase_orders"]),
                    ("StructureAgent", ["find_where_used"]),
                ]
            else:
                selected = []
            return json.dumps({"multi_agent": bool(selected), "agents": [
                {"agent_name": name, "task": f"核验{name}领域事实", "tools": tools}
                for name, tools in selected
            ]}, ensure_ascii=False)
        return json.dumps({
            "judgment": "已核验的领域事实需要审慎评估，尚未核验的信息不作确定结论。",
            "recommendations": ["核验缺口后再决定是否启动正式流程。"],
        }, ensure_ascii=False)

    def invoke_with_tools(self, *, messages: object, tools: object) -> AIMessage:
        return AIMessage(content="这是通用概念问题；BOM 是物料清单，ECR 是变更请求，ECO 是变更订单。")


def _cleanup(run_id: uuid.UUID) -> None:
    with create_session() as session:
        session.execute(delete(ToolCall).where(ToolCall.run_id == run_id))
        session.execute(delete(AgentStep).where(AgentStep.run_id == run_id))
        session.execute(delete(AgentRun).where(AgentRun.run_id == run_id))
        session.commit()


def run_case(case: object, llm: object) -> CaseEvaluation:
    trace_service = TraceService()
    run_id = uuid.uuid4()
    trace_service.create_run(run_id, workflow_name="assistant_benchmark")
    clock = perf_counter()
    try:
        tools = None
        if case.simulate_tool_failure:
            def fail_inventory(**kwargs: object) -> str:
                raise RuntimeError("controlled benchmark Tool failure")

            tools = [
                StructuredTool.from_function(
                    func=fail_inventory, name="get_inventory",
                    description="Controlled failure for benchmark safety verification.",
                    args_schema=GetInventoryInput,
                ) if tool.name == "get_inventory" else tool
                for tool in get_enterprise_tools()
            ]
        assistant = EnterpriseAssistant(llm_client=llm, trace_service=trace_service, tools=tools)
        context = AssistantService._extract_context(case.question, AssistantContext())
        error_type = None
        try:
            answer = assistant.answer(case.question, context, [], run_id)
            trace_service.update_run_status(run_id, "SUCCEEDED")
        except Exception as exc:  # noqa: BLE001 - isolate one benchmark case
            error_type = type(exc).__name__
            trace_service.update_run_status(run_id, "FAILED", error=str(exc)[:500])
            answer = AssistantAnswer(
                text="模型或业务查询失败。", tool_names=[], context=context,
                facts=[], failed=True, status="LLM_ERROR",
            )
        elapsed = int((perf_counter() - clock) * 1000)
        with create_session() as session:
            calls = list(session.scalars(select(ToolCall).where(ToolCall.run_id == run_id)))
            steps = list(session.scalars(select(AgentStep).where(AgentStep.run_id == run_id)))
            actual_tools = [call.tool_name for call in calls]
            actual_agents = [step.node_name for step in steps if step.node_name.endswith("Agent")]
            used_supervisor = any(step.node_name == "supervisor_plan" for step in steps)
        suggestion = AssistantService._suggest(case.question, answer.context, answer.facts, answer.failed)
        result = evaluate_case(
            case, answer, actual_tools=actual_tools, actual_agents=actual_agents,
            used_supervisor=used_supervisor,
            suggestion=suggestion.workflow if suggestion else None,
            latency_ms=elapsed,
        )
        result.error_type = error_type
        return result
    finally:
        _cleanup(run_id)


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run_benchmark(
    *, real_llm: bool = False, limit: int | None = None,
    output_dir: Path | None = None,
) -> dict[str, object]:
    cases = load_cases()[:limit]
    llm = DeepSeekLLMClient() if real_llm else FakeAssistantLLM()
    with nullcontext() if real_llm else without_tracing():
        results = [run_case(case, llm) for case in cases]
    metric_names = tuple(results[0].metrics) if results else ()
    summary = {
        name: round(sum(result.metrics[name] for result in results) / len(results), 3)
        for name in metric_names
    }
    report: dict[str, object] = {
        "benchmark": "ChangePilot-V2.8-Core", "timestamp_utc": datetime.now(UTC).isoformat(),
        "mode": "real" if real_llm else "fake", "model": getattr(llm, "_model", "controlled-fake"),
        "git_commit": _git_commit(), "langsmith_project": langsmith_project() if real_llm else None,
        "case_count": len(results), "passed": sum(result.passed for result in results),
        "failed": sum(not result.passed for result in results),
        "metrics": summary,
        "average_latency_ms": round(sum(result.latency_ms for result in results) / len(results), 1)
        if results else 0,
        "cases": [result.model_dump() for result in results],
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "assistant_v28.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        lines = [
            "# ChangePilot V2.8 Assistant Benchmark", "",
            f"模式：{report['mode']}；Case：{len(results)}；通过：{report['passed']}；失败：{report['failed']}",
            "", "| 指标 | 得分 |", "| --- | ---: |",
            *(f"| {name} | {score:.3f} |" for name, score in summary.items()),
            f"| average_latency_ms | {report['average_latency_ms']} |", "",
            "| Case | 结果 | 问题 |", "| --- | --- | --- |",
            *(f"| {item.case_id} | {'PASS' if item.passed else 'FAIL'} | {'；'.join(item.issues)} |"
              for item in results), "",
        ]
        (output_dir / "assistant_v28.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="ChangePilot V2.8 Assistant Benchmark")
    parser.add_argument("--real-llm", action="store_true", help="显式调用 DeepSeek")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    report = run_benchmark(real_llm=args.real_llm, limit=args.limit, output_dir=args.output_dir)
    print(json.dumps({key: report[key] for key in (
        "mode", "case_count", "passed", "failed", "metrics", "average_latency_ms",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
