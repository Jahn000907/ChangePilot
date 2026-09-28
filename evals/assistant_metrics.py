"""Deterministic Assistant benchmark contracts and metrics; no model judge for facts."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.enterprise_assistant import AssistantAnswer, EnterpriseAssistant, ToolFact

DATASET_PATH = Path(__file__).parent / "benchmarks" / "assistant_core_v28.json"
METRIC_NAMES = (
    "tool_selection_accuracy", "agent_selection_precision", "agent_selection_recall",
    "agent_selection_exact", "supervisor_routing_accuracy", "fact_grounding_rate",
    "unsupported_fact_rate", "workflow_suggestion_accuracy", "task_completion_rate",
)
_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w-])\d+(?:\.\d+)?(?![\w-])")


class AssistantBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    question: str
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_agents: list[str] = Field(default_factory=list)
    forbidden_agents: list[str] = Field(default_factory=list)
    should_use_supervisor: bool = False
    expected_facts: dict[str, str | int | float] = Field(default_factory=dict)
    forbidden_facts: list[str] = Field(default_factory=list)
    expected_workflow_suggestion: Literal["supplier_eol", "material_substitution"] | None = None
    expected_status: Literal["SUCCESS", "NO_DATA", "TOOL_ERROR"] = "SUCCESS"
    simulate_tool_failure: bool = False
    notes: str = ""


class CaseEvaluation(BaseModel):
    case_id: str
    passed: bool
    metrics: dict[str, float]
    issues: list[str]
    actual_tools: list[str]
    actual_agents: list[str]
    actual_suggestion: str | None
    answer_status: str
    latency_ms: int
    answer_preview: str
    evidence_preview: str = ""
    error_type: str | None = None


def load_cases(path: Path = DATASET_PATH) -> list[AssistantBenchmarkCase]:
    cases = [AssistantBenchmarkCase.model_validate(item) for item in json.loads(
        path.read_text(encoding="utf-8"),
    )["cases"]]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Benchmark case_id 不唯一")
    return cases


def _evidence(facts: list[ToolFact], question: str) -> str:
    fragments = [question]
    for fact in facts:
        fragments.append(json.dumps(fact.data, ensure_ascii=False, default=str))
        try:
            fragments.append(EnterpriseAssistant._format_fact(fact, question))
        except (KeyError, TypeError, ValueError):
            # Raw Tool output still provides evidence if formatting is incomplete.
            pass
    return " ".join(fragments)


def _unsupported(answer: str, evidence: str, *, check_numbers: bool = True) -> list[str]:
    # Exclude Markdown enumerator numbers, not business quantities.
    prose = re.sub(r"(?m)^\s*\d+[.)、]\s*", "", answer)
    # Enterprise identifiers carry digits; hyphenated generic terms such as
    # "Where-Used" are not claims about a concrete company record.
    codes = {code.upper() for code in _CODE.findall(prose) if any(char.isdigit() for char in code)}
    unsupported = {code for code in codes if code not in evidence.upper()}
    known_numbers = set(_NUMBER.findall(evidence))
    known_decimals: set[Decimal] = set()
    for item in known_numbers:
        try:
            known_decimals.add(Decimal(item))
        except InvalidOperation:
            pass
    for item in _NUMBER.findall(prose) if check_numbers else []:
        try:
            if Decimal(item) not in known_decimals:
                unsupported.add(item)
        except InvalidOperation:
            unsupported.add(item)
    return sorted(unsupported)


def _same_value(left: object, right: object) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return str(left).upper() == str(right).upper()


def _has_expected_fact(data: object, key: str, value: object) -> bool:
    if isinstance(data, dict):
        if key in data and _same_value(data[key], value):
            return True
        # Alternative part + qualification must belong to the same row.
        if (key in {str(item) for item in data.values() if isinstance(item, str)}
                and any(_same_value(item, value) for item in data.values())):
            return True
        return any(_has_expected_fact(item, key, value) for item in data.values())
    if isinstance(data, list):
        return any(_has_expected_fact(item, key, value) for item in data)
    return False


def evaluate_case(
    case: AssistantBenchmarkCase, answer: AssistantAnswer, *,
    actual_tools: list[str], actual_agents: list[str], used_supervisor: bool,
    suggestion: str | None, latency_ms: int,
) -> CaseEvaluation:
    tools = set(actual_tools) - {"get_part_revisions"}
    agents = set(actual_agents)
    required_tools, required_agents = set(case.expected_tools), set(case.expected_agents)
    missing_tools = required_tools - tools
    extra_tools = (tools - required_tools) | (tools & set(case.forbidden_tools))
    missing_agents = required_agents - agents
    extra_agents = (agents - required_agents) | (agents & set(case.forbidden_agents))
    tool_score = (
        len(required_tools & tools) / len(required_tools | tools)
        if required_tools or tools else 1.0
    )
    precision = len(required_agents & agents) / len(agents) if agents else (1.0 if not required_agents else 0.0)
    recall = len(required_agents & agents) / len(required_agents) if required_agents else (1.0 if not agents else 0.0)
    exact = float(agents == required_agents and not extra_agents)
    evidence = _evidence(answer.facts, case.question)
    unsupported = _unsupported(answer.text, evidence, check_numbers=case.category != "general")
    expected_missing = [
        f"{key}={value}" for key, value in case.expected_facts.items()
        if not any(_has_expected_fact(fact.data, key, value) for fact in answer.facts)
    ]
    forbidden_found = [value for value in case.forbidden_facts if value in answer.text]
    grounding = 1.0 if not unsupported else max(0.0, 1 - len(unsupported) / max(1, len(_CODE.findall(answer.text)) + len(_NUMBER.findall(answer.text))))
    task_complete = float(
        not expected_missing and not forbidden_found
        and not missing_tools and not extra_tools and not missing_agents and not extra_agents
        and not unsupported and used_supervisor == case.should_use_supervisor
        and suggestion == case.expected_workflow_suggestion
        and answer.status == case.expected_status
        and (not answer.facts if case.simulate_tool_failure else True)
    )
    metrics = dict(zip(METRIC_NAMES, (
        tool_score, precision, recall, exact, float(used_supervisor == case.should_use_supervisor),
        grounding, 1.0 - grounding, float(suggestion == case.expected_workflow_suggestion),
        task_complete,
    ), strict=True))
    issues = [
        *[f"缺少 Tool: {name}" for name in sorted(missing_tools)],
        *[f"误调用 Tool: {name}" for name in sorted(extra_tools)],
        *[f"缺少 Agent: {name}" for name in sorted(missing_agents)],
        *[f"误调用 Agent: {name}" for name in sorted(extra_agents)],
        *[f"无证据事实: {value}" for value in unsupported],
        *[f"缺少期望事实: {value}" for value in expected_missing],
        *[f"出现禁止事实: {value}" for value in forbidden_found],
    ]
    if used_supervisor != case.should_use_supervisor:
        issues.append("Supervisor 路由不符")
    if suggestion != case.expected_workflow_suggestion:
        issues.append("Workflow Suggestion 不符")
    if not task_complete:
        issues.append(f"任务未完成: {answer.status}")
    return CaseEvaluation(
        case_id=case.case_id, passed=not issues, metrics=metrics, issues=issues,
        actual_tools=actual_tools, actual_agents=actual_agents, actual_suggestion=suggestion,
        answer_status=answer.status, latency_ms=latency_ms, answer_preview=answer.text[:1000],
        evidence_preview=evidence[:4000],
    )
