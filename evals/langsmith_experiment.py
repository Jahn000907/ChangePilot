"""Opt-in LangSmith Experiment on a synced subset of the fixed benchmark."""

from __future__ import annotations

import argparse

from app.llm.client import DeepSeekLLMClient
from evals.assistant_metrics import AssistantBenchmarkCase, load_cases
from evals.judge import judge_answer
from evals.langsmith_dataset import DATASET_NAME, configured_client
from evals.run import FakeAssistantLLM, run_case


def run_experiment(*, limit: int = 2, real_llm: bool = False, judge: bool = False) -> str:
    client = configured_client()
    by_id = {
        str(example.inputs.get("case_id")): example
        for example in client.list_examples(dataset_name=DATASET_NAME)
    }
    examples = [by_id[case.case_id] for case in load_cases() if case.case_id in by_id][:limit]
    if not examples:
        raise RuntimeError("LangSmith Dataset 为空；请先显式运行 evals.langsmith_dataset。")
    llm = DeepSeekLLMClient() if real_llm else FakeAssistantLLM()
    judge_llm = DeepSeekLLMClient() if judge else None

    def target(inputs: dict[str, object]) -> dict[str, object]:
        example = next(item for item in examples if item.inputs["case_id"] == inputs["case_id"])
        case = AssistantBenchmarkCase.model_validate({
            **example.outputs, "case_id": inputs["case_id"],
            "question": inputs["question"], "category": example.metadata.get("category", "general"),
        })
        return run_case(case, llm).model_dump()

    def deterministic(run: object, example: object) -> list[dict[str, object]]:
        outputs = getattr(run, "outputs", None) or {}
        scores = outputs.get("metrics") or {}
        return [
            {"key": "deterministic_pass", "score": float(bool(outputs.get("passed")))},
            *({"key": key, "score": float(value)} for key, value in scores.items()),
        ]

    evaluators = [deterministic]
    if judge_llm is not None:
        def qualitative(run: object, example: object) -> list[dict[str, object]]:
            inputs = getattr(example, "inputs", None) or {}
            outputs = getattr(run, "outputs", None) or {}
            result = judge_answer(
                judge_llm, question=str(inputs["question"]),
                answer=str(outputs.get("answer_preview", "")),
                evidence=str(outputs.get("evidence_preview", "")),
            )
            return [{"key": key, "score": getattr(result, key), "comment": result.comment}
                    for key in ("grounded_analysis", "completeness", "clarity")]
        evaluators.append(qualitative)
    results = client.evaluate(
        target, data=examples, evaluators=evaluators,
        experiment_prefix="ChangePilot-V2.8", max_concurrency=1, blocking=True,
        metadata={"mode": "real" if real_llm else "fake", "judge": judge},
    )
    return str(results.experiment_name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--real-llm", action="store_true")
    parser.add_argument("--judge", action="store_true")
    args = parser.parse_args()
    print(f"LangSmith Experiment: {run_experiment(limit=args.limit, real_llm=args.real_llm, judge=args.judge)}")


if __name__ == "__main__":
    main()
