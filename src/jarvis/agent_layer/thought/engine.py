from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from jarvis.agent_layer.thought.prompt import ThoughtPromptTemplate
from jarvis.agent_layer.thought.protocol import RecallFn
from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.model_layer.stream import stream_to_message
from jarvis.model_layer.types import (
    LLMContext,
    Message,
    ModelConfig,
    StreamOptions,
    UserMessage,
)


class InnerThoughtEngine:
    """
    기본 `ThoughtEngine` 구현 — 메인 응답과 분리된 별도 LLM 호출로
    구조화된 `ThoughtFrame`을 생성한다.

    독립 객체로 격리했으므로 고도화는 두 축으로 가능하다:
    1. 통째 교체   — `ThoughtEngine` Protocol을 구현하는 다른 클래스로 swap.
    2. 부분 확장   — 아래 `_`-prefixed seam 메서드(_recall/_render/_call_model/
       _parse)를 서브클래스에서 오버라이드.

    `model_layer`에만 의존한다(Hard Rule #1). 오케스트레이션·정책은 core가 맡는다.
    """

    def __init__(
        self,
        model: ModelConfig,
        template: ThoughtPromptTemplate | None = None,
        recall: RecallFn | None = None,
        recall_limit: int = 5,
        skip_if_shorter_than: int = 0,
        history_window: int = 12,
        clock: Callable[[], datetime] | None = None,
        reflection_template: ThoughtPromptTemplate | None = None,
    ) -> None:
        self._model = model
        self._template = template or ThoughtPromptTemplate()
        # 성찰 전용 템플릿(mode="reflection"). 미지정 시 요청용 템플릿으로 폴백.
        self._reflection_template = reflection_template or self._template
        self._recall = recall
        self._recall_limit = recall_limit
        self._skip_if_shorter_than = skip_if_shorter_than
        self._history_window = history_window
        self._clock = clock or datetime.now

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        # 짧은 입력(인사 등)은 사고 생략 — 지연/비용 완화. 성찰은 적용 제외.
        if request.mode != "reflection" and (
            len(request.user_input.strip()) < self._skip_if_shorter_than
        ):
            return None

        recalled = await self._recall_memories(request)
        prompt = self._render(request, recalled)

        try:
            raw = await self._call_model(prompt)
        except Exception:
            # 사고는 부가 기능 — 모델 호출 실패는 조용히 생략한다.
            return None

        return self._parse(raw)

    # ── override seams ─────────────────────────────────────────────────────────

    async def _recall_memories(self, request: ThoughtRequest) -> list[str]:
        """회상 콜백으로 관련 기억을 요약 문자열 목록으로 변환."""
        if self._recall is None:
            return []
        try:
            messages = await self._recall(
                request.user_input,
                {"session_id": request.session_id},
                self._recall_limit,
            )
        except Exception:
            return []
        return [_message_text(m) for m in messages if _message_text(m)]

    def _render(self, request: ThoughtRequest, recalled: list[str]) -> str:
        template = (
            self._reflection_template
            if request.mode == "reflection"
            else self._template
        )
        external = "\n".join(f"- {x}" for x in request.external_events)
        rendered = template.render(
            now=self._clock().isoformat(timespec="seconds"),
            open_loops="\n".join(f"- {x}" for x in request.open_loops),
            external_events=external,
            recalled_memories="\n".join(f"- {x}" for x in recalled),
            history=self._format_history(request.history),
            user_input=request.user_input,
            user_model=request.user_model,
        )
        # 템플릿 드리프트 방어 — 사용자가 이미 편집한 템플릿엔 새 플레이스홀더가
        # 없다. 이벤트가 있는데 자리가 없으면 뒤에 덧붙여 조용한 유실을 막는다.
        if external and not template.has_placeholder("external_events"):
            rendered = f"{rendered}\n\n[외부 이벤트]\n{external}"
        return rendered

    async def _call_model(self, prompt: str) -> str:
        """단발 LLM 호출. 사고 전용이므로 툴 없이 텍스트만 받는다."""
        ctx = LLMContext(messages=[UserMessage(content=prompt)], tools=None)
        msg = await stream_to_message(self._model, ctx, StreamOptions())
        return msg.text()

    def _parse(self, raw: str) -> ThoughtFrame | None:
        """모델 출력에서 JSON을 추출해 검증. 실패 시 graceful fallback(None)."""
        payload = _extract_json(raw)
        if payload is None:
            return None
        try:
            return ThoughtFrame.model_validate(payload)
        except Exception:
            return None

    def _format_history(self, history: list[Message]) -> str:
        recent = history[-self._history_window :]
        lines: list[str] = []
        for m in recent:
            text = _message_text(m)
            if text:
                lines.append(f"{m.role}: {text}")
        return "\n".join(lines)


def _message_text(message: Message, max_chars: int = 400) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return str(content[:max_chars])
    if isinstance(content, list):
        parts = [str(getattr(b, "text", "")) for b in content if getattr(b, "text", "")]
        return " ".join(parts)[:max_chars]
    return ""


def _extract_json(raw: str) -> dict[str, Any] | None:
    """코드펜스/잡텍스트에 둘러싸인 JSON 객체를 관대하게 추출."""
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
