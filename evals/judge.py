"""Optional qualitative rubric; never substitutes deterministic fact checks."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.llm.client import LLMClient


class JudgeResult(BaseModel):
    grounded_analysis: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    clarity: float = Field(ge=0, le=1)
    comment: str = Field(max_length=500)


def judge_answer(llm: LLMClient, *, question: str, answer: str, evidence: str) -> JudgeResult:
    raw = llm.generate_json(
        system_prompt=(
            "你只评估分析与表达质量，不判断库存数值、编号或其他客观事实正确性。"
            "仅根据给出的 evidence 评价 grounded_analysis、completeness、clarity，"
            "各给 0 到 1 分；返回 JSON，包含这三个字段和简短 comment。"
        ),
        user_prompt=json.dumps({
            "question": question, "answer": answer[:3000], "evidence": evidence[:4000],
        }, ensure_ascii=False),
    )
    return JudgeResult.model_validate_json(raw)
