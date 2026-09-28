"""Explicit, idempotent sync of fixed local cases to a LangSmith dataset."""

from __future__ import annotations

import argparse

from langsmith import Client

from app.llm.tracing import LangSmithSettings
from evals.assistant_metrics import load_cases

DATASET_NAME = "ChangePilot-V2.8-Core"


def configured_client() -> Client:
    settings = LangSmithSettings()
    key = settings.langsmith_api_key.get_secret_value().strip() if settings.langsmith_api_key else ""
    if not key:
        raise RuntimeError("缺少 LANGSMITH_API_KEY；本地 Benchmark 不受影响。")
    return Client(api_key=key)


def sync_dataset(*, limit: int | None = None, client: Client | None = None) -> tuple[str, int]:
    remote = client or configured_client()
    if remote.has_dataset(dataset_name=DATASET_NAME):
        dataset = remote.read_dataset(dataset_name=DATASET_NAME)
    else:
        dataset = remote.create_dataset(
            DATASET_NAME, description="ChangePilot V2.8 fixed Assistant and Multi-Agent cases",
        )
    existing = {
        str(example.inputs.get("case_id")): example
        for example in remote.list_examples(dataset_id=dataset.id)
    }
    synced = 0
    for case in load_cases()[:limit]:
        inputs = {"case_id": case.case_id, "question": case.question}
        outputs = case.model_dump(exclude={"question", "notes", "category"})
        metadata = {"category": case.category, "notes": case.notes, "benchmark_version": "2.8"}
        if case.case_id in existing:
            remote.update_example(existing[case.case_id].id, inputs=inputs, outputs=outputs,
                                  metadata=metadata)
        else:
            remote.create_example(inputs=inputs, outputs=outputs, metadata=metadata,
                                  dataset_id=dataset.id)
        synced += 1
    return DATASET_NAME, synced


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    name, count = sync_dataset(limit=args.limit)
    print(f"LangSmith Dataset {name}: 已同步 {count} 条 Case")


if __name__ == "__main__":
    main()
