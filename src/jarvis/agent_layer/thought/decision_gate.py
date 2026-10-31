"""[agent_layer] 성찰 사고의 "먼저 말할까" 판단을 decision model 의 확률로 정하는 ThoughtEngine 래퍼."""

from typing import Any
from datetime import datetime
from collections.abc import Callable

from jarvis.model_layer.model_types import LLMContext, Message, ModelConfig, StreamOptions, UserMessage
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.thought_protocol import ThoughtEngine
from jarvis.model_layer.stream import stream_to_message
from jarvis.model_layer.decision import DecisionModel

# 이 값보다 낮으면 바로 침묵으로 두고 건넬 말을 만들지 않는다. 그 위에서 실제로 말할지는 정책 임계치가 정한다.
# decision model 을 쓰면 정책 임계치는 JARVIS_PROACTIVE__DECISION_THRESHOLD 다(ProactiveConfig.effective_threshold)
UTTERANCE_FLOOR = 0.3
HISTORY_TURNS = 6
HISTORY_CHARS = 200
SPEAK_QUESTION = "지금 사용자에게 먼저 말을 거는 것이 사용자에게 실제로 도움이 되는가"
SPEAK_NO = "말을 걸지 않는 것이 낫다. 알릴 것이 없거나, 이미 끝났거나, 사용자와 관계없거나, 아직 한참 남은 일이다"
SPEAK_YES = "지금 먼저 알려야 한다. 기한이 다가오거나 지났거나, 사용자의 일에 직접 영향을 주는 일이 생겼다"
# 알릴 거리가 없을 때 빈 답을 허락하지 않으면 모델이 인사("안녕하세요! 더 궁금한 점 있으시면…")를 지어 🔔 로 보낸다
UTTERANCE_PROMPT = """\
아래 상황에서 사용자에게 먼저 건넬 한두 문장만 써라. 사용자를 분석하는 문장이 아니라 말을 거는 문장으로 쓴다.
설명이나 따옴표 없이 문장만 출력한다.
알릴 구체적인 것(다가온 기한, 새 소식, 챙길 일)이 없으면 아무것도 출력하지 않는다. 인사, 안부,
"더 궁금한 점 있으면 말씀해 주세요" 같은 말만 건네는 문장은 쓰지 않는다.

[말투] {persona}
[지금] {now}
[열린 약속] {open_loops}
[외부 이벤트] {external_events}
[최근 대화]
{history}
"""


def _text(message: Message) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    text = getattr(message, "text", None)
    return text() if callable(text) else ""


def decision_state(request: ThoughtRequest, now: datetime) -> dict[str, Any]:
    """decision model 에 넘길 상태. 사고 프롬프트와 같은 재료를 짧게 담는다. 순수 함수다."""
    turns = [f"{m.role}: {_text(m)[:HISTORY_CHARS]}" for m in request.history[-HISTORY_TURNS:]]
    return {
        "now": now.isoformat(timespec="minutes"),
        "recent_conversation": turns,
        "open_promises": request.open_loops,
        "external_events": request.external_events,
        "already_said_recently": request.recent_proactive,
    }


class DecisionGatedEngine(ThoughtEngine):
    """요청 사고는 그대로 두고, 성찰 사고만 decision model 의 확률로 결정과 확신도를 바꾼다.

    decision model 이 실패하면 안쪽 엔진의 프레임을 그대로 쓴다. 말하기로 했는데 건넬 말이 비어 있으면
    utterance_model 로 한두 문장을 만든다(그때만 LLM 을 한 번 더 부른다).
    """

    def __init__(
        self,
        inner: ThoughtEngine,
        decision: DecisionModel,
        utterance_model: ModelConfig,
        clock: Callable[[], datetime] | None = None,
        floor: float = UTTERANCE_FLOOR,
        persona: str = "",
    ) -> None:
        self._inner = inner
        self._persona = persona
        self._floor = floor
        self._decision = decision
        self._utterance_model = utterance_model
        self._clock = clock or datetime.now

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        frame = await self._inner.think(request)
        if request.mode != "reflection" or frame is None:
            return frame
        state = decision_state(request, self._clock())
        p = await self._decision.yes_probability(state, SPEAK_QUESTION, SPEAK_NO, SPEAK_YES)
        if p is None:
            return frame
        speak = p >= self._floor
        utterance = frame.utterance if speak else ""
        if speak and not utterance.strip():
            utterance = await self._utterance(state)
        return frame.model_copy(
            update={
                # 안쪽 사고가 ask 로 정했으면 되묻는 성격을 남긴다
                "decision": (frame.decision if frame.decision in ("act", "ask") else "act")
                if speak and utterance
                else "silent",
                "confidence": p,
                "utterance": utterance,
                "rationale": f"{frame.rationale} [decision {self._decision.model} p={p:.2f}]".strip(),
            }
        )

    async def _utterance(self, state: dict[str, Any]) -> str:
        prompt = UTTERANCE_PROMPT.format(
            persona=self._persona or "(없음)",
            now=state["now"],
            open_loops=", ".join(state["open_promises"]) or "(없음)",
            external_events=", ".join(state["external_events"]) or "(없음)",
            history="\n".join(state["recent_conversation"]) or "(없음)",
        )
        message = await stream_to_message(
            self._utterance_model, LLMContext(messages=[UserMessage(content=prompt)]), StreamOptions()
        )
        return "" if message.error_message else message.text().strip()
