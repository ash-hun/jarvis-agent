"""의미 추출. 일화(세션 요약)에서 '주제: 값' 사실을 뽑는다. 반복된 경험이 일반 지식으로 추상화되는 자리."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jarvis.model_layer.types import LLMContext, ModelConfig, StreamOptions, UserMessage


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    importance: float = 0.5

    @property
    def content(self) -> str:
        return f"{self.key}: {self.value}"


# 일화 본문 → 사실 후보. 실패하면 빈 목록(호출자는 아무것도 쓰지 않는다).
FactExtractor = Callable[[str], Awaitable[list[Fact]]]

PROMPT = """\
아래 대화 요약에서 앞으로도 참이고 다시 쓸 만한 사실만 뽑아라. 사용자에 대한 사실(선호, 상황, 관계),
프로젝트나 환경에 대한 사실이 대상이다. 일회성 사건이나 감정은 제외한다.

JSON 배열로만 답하라. 각 원소는 {{"key": "주제(명사구, 짧게)", "value": "값", "importance": 0.0~1.0}}.
같은 주제가 여러 번 나오면 가장 최신 값 하나만. 없으면 [].

[요약]
{summary}
"""


def parse_facts(raw: str) -> list[Fact]:
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    facts: list[Fact] = []
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        key, value = str(row.get("key", "")).strip(), str(row.get("value", "")).strip()
        if not key or not value:
            continue
        try:
            importance = float(row.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        facts.append(Fact(key=key, value=value, importance=min(1.0, max(0.0, importance))))
    return facts


def llm_fact_extractor(model: ModelConfig) -> FactExtractor:
    async def extract(summary: str) -> list[Fact]:
        from jarvis.model_layer.stream import stream_to_message

        ctx = LLMContext(messages=[UserMessage(content=PROMPT.format(summary=summary))], tools=None)
        result = await stream_to_message(model, ctx, StreamOptions())
        if result.error_message is not None:
            return []
        return parse_facts(result.text())

    return extract
