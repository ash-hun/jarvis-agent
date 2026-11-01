"""[core] 먼저 건넨 말(🔔)을 블라인드 LLM 판정자가 누출 라벨과 근거 구간으로 분류하는 평가 도구."""

# 운영 경로에서 쓰지 않는다. 판정자는 말과 직전 답만 보고, 어느 구성이 만든 말인지 모른다.
# 판정 출력은 신뢰하지 않는 입력이라 스키마로 검증하고, 근거 구간이 말 안에 실제로 있는지 코드가 확인한다.

import json
from typing import Literal
from collections.abc import Sequence
from pydantic import BaseModel, ValidationError

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamOptions, UserMessage
from jarvis.agent_layer.thought.engine import extract_json
from jarvis.model_layer.stream import stream_to_message

UtteranceLabel = Literal["greeting_only", "restates_answer", "user_analysis_leak", "concrete_notice", "unclear"]
LABELS: tuple[UtteranceLabel, ...] = (
    "greeting_only",
    "restates_answer",
    "user_analysis_leak",
    "concrete_notice",
    "unclear",
)
JUDGE_PROMPT = """\
비서가 사용자에게 먼저 건넨 말 하나를 분류한다. 아래 다섯 라벨 중 정확히 하나를 고르고, 그 라벨의 근거가 되는
구간을 [먼저 건넨 말]에서 글자 그대로 복사한다.

- greeting_only: 인사, 안부, "더 궁금한 점 있으면 말씀해 주세요" 처럼 알리는 내용이 없다
- restates_answer: [직전 답]의 내용을 다시 말할 뿐 새로 알리는 것이 없다
- user_analysis_leak: 사용자에게 말을 거는 것이 아니라 사용자를 3인칭으로 분석하거나 비서 자신의 판단 과정을 적었다
  (예: "사용자는 지금 쉬고 있는 것으로 보인다", "알릴 필요가 있다고 판단된다")
- concrete_notice: 사용자에게 말을 걸며 구체적인 것(시각, 기한, 금액, 실패, 변경, 할 일)을 알린다
- unclear: 위 어느 것으로도 확실히 고를 수 없다

[직전 답] {last_answer}
[먼저 건넨 말] {utterance}

JSON 하나만 출력한다: {{"label": "<라벨>", "evidence": "<먼저 건넨 말에서 복사한 구간>"}}
"""
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": list(LABELS)}, "evidence": {"type": "string"}},
    "required": ["label", "evidence"],
}


class UtteranceVerdict(BaseModel):
    label: UtteranceLabel
    evidence: str = ""
    evidence_found: bool = False  # 근거 구간이 말 안에 글자 그대로 있는가


def parse_verdict(raw: str, utterance: str) -> UtteranceVerdict | None:
    """판정자 출력에서 라벨과 근거를 꺼내 검증한다. 형식이 틀리면 None. 순수 함수."""
    payload = extract_json(raw)
    if payload is None:
        return None
    try:
        verdict = UtteranceVerdict.model_validate(
            {"label": payload.get("label"), "evidence": payload.get("evidence", "")}
        )
    except ValidationError:
        return None
    found = bool(verdict.evidence.strip()) and verdict.evidence.strip() in utterance
    return verdict.model_copy(update={"evidence_found": found})


def agreement_by_label(human: Sequence[UtteranceLabel], judged: Sequence[UtteranceLabel | None]) -> dict[str, float]:
    """사람 라벨마다 판정자가 같은 라벨을 고른 비율과 전체 일치율("all"). 사람 라벨이 없는 라벨은 빠진다. 순수 함수."""
    pairs = list(zip(human, judged, strict=True))
    out: dict[str, float] = {}
    for label in LABELS:
        rows = [j for h, j in pairs if h == label]
        if rows:
            out[label] = sum(j == label for j in rows) / len(rows)
    if pairs:
        out["all"] = sum(h == j for h, j in pairs) / len(pairs)
    return out


class UtteranceJudge:
    """말 하나를 라벨 하나로. 모델 호출이나 형식이 실패하면 None."""

    def __init__(self, model: ModelConfig) -> None:
        self._model = model

    async def judge(self, utterance: str, last_answer: str = "") -> UtteranceVerdict | None:
        prompt = JUDGE_PROMPT.format(
            utterance=json.dumps(utterance, ensure_ascii=False), last_answer=last_answer or "(없음)"
        )
        message = await stream_to_message(
            self._model, LLMContext(messages=[UserMessage(content=prompt)]), StreamOptions(json_schema=JUDGE_SCHEMA)
        )
        if message.error_message:
            return None
        return parse_verdict(message.text(), utterance)
