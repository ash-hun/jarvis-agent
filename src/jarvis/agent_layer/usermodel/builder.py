from __future__ import annotations

import json

from jarvis.agent_layer.usermodel.types import UserModel
from jarvis.model_layer.stream import stream_to_message
from jarvis.model_layer.types import LLMContext, ModelConfig, StreamOptions, UserMessage

DEFAULT_PROMPT = """\
너는 사용자의 "안정적 모델"을 갱신하는 증류기다. 아래 누적 기억과 이전 모델을 보고,
오래 가는 특성(선호·작업 방식·반복 패턴·관심사)만 추려 JSON 하나만 출력하라.
일회성 사실·휘발적 문맥은 제외한다. JSON 외 텍스트 금지.

[이전 모델]
{previous}

[누적 기억]
{sources}

다음 키를 가진 JSON 객체 하나만 출력하라:
- summary (string): 사용자를 한 문단으로 요약
- traits (string[]): 선호·작업 방식·반복 패턴 항목 (간결하게, 최대 8개)

원칙: 근거가 약하면 넣지 마라. 이전 모델을 보존하되 새 근거로 보강·수정하라.
"""


class UserModelBuilder:
    """누적 기억(LTM 요약·사고 로그 등)을 LLM으로 증류해 UserModel을 갱신 (D1).

    InnerThoughtEngine과 동일한 단발 호출 + JSON 파싱 + graceful fallback 패턴.
    """

    def __init__(self, model: ModelConfig, prompt: str = DEFAULT_PROMPT) -> None:
        self._model = model
        self._prompt = prompt

    async def build(
        self, sources: list[str], previous: UserModel | None = None
    ) -> UserModel | None:
        sources = [s for s in (x.strip() for x in sources) if s]
        if not sources:
            return previous  # 증류할 게 없으면 기존 모델 유지

        rendered = self._prompt.format(
            previous=(previous.as_context() if previous else "(없음)"),
            sources="\n".join(f"- {s}" for s in sources),
        )
        try:
            raw = await self._call_model(rendered)
        except Exception:
            return previous

        payload = _extract_json(raw)
        if payload is None:
            return previous
        try:
            return UserModel(
                summary=str(payload.get("summary", "")),
                traits=[str(t) for t in payload.get("traits", []) if str(t).strip()],
                source_count=len(sources),
            )
        except Exception:
            return previous

    async def _call_model(self, prompt: str) -> str:
        ctx = LLMContext(messages=[UserMessage(content=prompt)], tools=None)
        msg = await stream_to_message(self._model, ctx, StreamOptions())
        return msg.text()


def _extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
