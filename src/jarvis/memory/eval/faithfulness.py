"""[memory] 대화에 심은 사실이 요약(/compact)을 거친 뒤에도 남아 있는 비율(retention)을 잰다."""

import json
from pathlib import Path
from pydantic import BaseModel, Field
from collections.abc import Awaitable, Callable

from jarvis.model_layer.model_types import (
    AssistantMessage,
    LLMContext,
    Message,
    ModelConfig,
    StreamOptions,
    TextContent,
    UserMessage,
)
from jarvis.memory.consolidation.compaction import Summarizer
from jarvis.memory.eval.metrics import CaseResult

# 요약기와 판정기는 주입한다. 오프라인 기본은 추출 요약기 + 문자열 포함 판정, 실제 측정은 --summarizer llm --judge llm
FactJudge = Callable[[str, str], Awaitable[bool]]  # (summary, fact) -> 보존됐는가
EXTRACTIVE_CHARS_PER_TURN = 200


class FaithfulnessTurn(BaseModel):
    role: str = "user"
    text: str


class FaithfulnessCase(BaseModel):
    suite: str = "faithfulness"
    case: str
    turns: list[FaithfulnessTurn]
    facts: list[str]  # 요약 뒤에도 남아야 하는 사실(판정기가 요약과 대조)
    min_retention: float = Field(default=0.8, ge=0.0, le=1.0)


def load_faithfulness_cases(path: Path) -> list[FaithfulnessCase]:
    return [
        FaithfulnessCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── 요약기와 판정기 ──────────────────────────────────────────────────────────


def extractive_summarizer(chars_per_turn: int = EXTRACTIVE_CHARS_PER_TURN) -> Summarizer:
    """LLM 없는 기준선. 사용자 턴을 앞에서부터 잘라 이어 붙인다. 이것보다 못하면 LLM 요약이 사실을 버리는 것이다."""

    async def summarize(messages: list[Message], prior: str | None) -> str:
        parts = [prior] if prior else []
        for m in messages:
            if m.role == "user" and isinstance(m.content, str):
                parts.append(m.content[:chars_per_turn])
        return " / ".join(parts)

    return summarize


def contains_fact_judge() -> FactJudge:
    async def judge(summary: str, fact: str) -> bool:
        return fact.strip().lower() in summary.lower()

    return judge


# 사실 칸은 문장이 아니라 단서 낱말("화요일", "1200만원")이다. "사실을 담는가" 로 물으면 모델이 낱말 하나를
# 사실로 보지 않아, 요약에 그대로 있어도 no 라고 했다. 낱말이 가리키는 정보가 있는지를 언어와 표기를 넘어 묻는다
JUDGE_PROMPT = """\
아래 [요약]에 [단서]가 가리키는 정보가 들어 있는지 판정하라.
- 다른 언어, 다른 표기, 다른 단위로 써도 같은 정보면 들어 있는 것이다
  (예: 서울 = Seoul, 오백만원 = 500만 원 = 5 million won, 3시 = 3 PM)
- 단서와 관련 없는 내용만 있으면 들어 있지 않은 것이다
yes 또는 no 한 단어로만 답하라.

[요약]
{summary}

[단서]
{fact}
"""


def llm_fact_judge(model: ModelConfig) -> FactJudge:
    async def judge(summary: str, fact: str) -> bool:
        from jarvis.model_layer.stream import stream_to_message

        ctx = LLMContext(messages=[UserMessage(content=JUDGE_PROMPT.format(summary=summary, fact=fact))], tools=None)
        verdict = (await stream_to_message(model, ctx, StreamOptions())).text().strip().lower()
        return verdict.startswith("y")

    return judge


# ── 실행 ──────────────────────────────────────────────────────────────────────


def _messages(case: FaithfulnessCase) -> list[Message]:
    out: list[Message] = []
    for i, turn in enumerate(case.turns):
        if turn.role == "assistant":
            out.append(AssistantMessage(content=[TextContent(text=turn.text)], timestamp=i))
        else:
            out.append(UserMessage(content=turn.text, timestamp=i))
    return out


async def run_faithfulness_case(case: FaithfulnessCase, summarizer: Summarizer, judge: FactJudge) -> CaseResult:
    """대화 전체를 요약해(/compact 와 같은 입력) 심어 둔 사실이 요약에 남는지 본다."""
    summary = await summarizer(_messages(case), None)
    if not summary:
        return CaseResult(suite=case.suite, case=case.case, passed=False, results=[], detail="no summary")
    kept = [fact for fact in case.facts if await judge(summary, fact)]
    missing = [fact for fact in case.facts if fact not in kept]
    retention = len(kept) / len(case.facts) if case.facts else 1.0
    return CaseResult(
        suite=case.suite,
        case=case.case,
        passed=retention >= case.min_retention,
        results=[summary[:300]],
        missing=missing,
        detail=f"retention={retention:.2f}",
        score=retention,
    )


async def run_faithfulness(cases: list[FaithfulnessCase], summarizer: Summarizer, judge: FactJudge) -> list[CaseResult]:
    return [await run_faithfulness_case(case, summarizer, judge) for case in cases]
