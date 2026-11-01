"""[agent_layer] 성찰의 "먼저 말할까" 를 decision model 로 먼저 정하고, 넘을 때만 사고와 발화를 만드는 엔진 래퍼."""

import asyncio
from typing import Any
from datetime import datetime
from collections.abc import Callable

from jarvis.model_layer.model_types import LLMContext, Message, ModelConfig, StreamOptions, UserMessage
from jarvis.agent_layer.thought.thought_types import SituationFact, ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.thought_protocol import ThoughtEngine
from jarvis.agent_layer.thought.anchor_check import anchor_present
from jarvis.agent_layer.thought.prompt import ANCHOR_LINE
from jarvis.model_layer.stream import stream_to_message
from jarvis.model_layer.decision import DecisionModel
from jarvis.common.logger import get_logger

logger = get_logger(__name__)

# 이 값보다 낮으면 사고 모델을 부르지 않고 침묵한다. 그 위에서 실제로 말할지는 정책 임계치가 정한다.
# decision model 을 쓰면 정책 임계치는 JARVIS_PROACTIVE__DECISION_THRESHOLD 다(ProactiveConfig.effective_threshold)
UTTERANCE_FLOOR = 0.3
HISTORY_TURNS = 6
HISTORY_CHARS = 200
# 항목별 질문 상한. 성찰 한 번의 decision model 호출은 1 + 이 값을 넘지 않는다
MAX_ITEM_QUESTIONS = 3
SPEAK_QUESTION = "지금 사용자에게 먼저 말을 거는 것이 사용자에게 실제로 도움이 되는가"
SPEAK_NO = "말을 걸지 않는 것이 낫다. 알릴 것이 없거나, 이미 끝났거나, 사용자와 관계없거나, 아직 한참 남은 일이다"
SPEAK_YES = "지금 먼저 알려야 한다. 기한이 다가오거나 지났거나, 사용자의 일에 직접 영향을 주는 일이 생겼다"
ITEM_QUESTION = "focus_item 은 아직 처리되지 않았고, 지금 사용자에게 먼저 알려야 하는 일인가"
ITEM_NO = "알릴 필요가 없다. 이미 처리됐거나(수락, 완료, 확인), 아직 한참 남았거나, 사용자와 관계없다"
ITEM_YES = "지금 알려야 한다. 아직 처리되지 않았고, 기한이 다가오거나 지났거나, 사용자의 일에 직접 영향을 준다"
# 알릴 거리가 없을 때 빈 답을 허락하지 않으면 모델이 인사("안녕하세요! 더 궁금한 점 있으시면…")를 지어 🔔 로 보낸다
UTTERANCE_PROMPT = """\
아래 상황에서 사용자에게 먼저 건넬 한두 문장만 써라. 사용자를 분석하는 문장이 아니라 말을 거는 문장으로 쓴다.
설명이나 따옴표 없이 문장만 출력한다.
알릴 구체적인 것(다가온 기한, 새 소식, 챙길 일)이 없으면 아무것도 출력하지 않는다. 인사, 안부,
"더 궁금한 점 있으면 말씀해 주세요" 같은 말만 건네는 문장은 쓰지 않는다.

{anchor}[말투] {persona}
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


def decision_state(request: ThoughtRequest, now: datetime, with_facts: bool = False) -> dict[str, Any]:
    """decision model 에 넘길 상태. 사고 프롬프트의 재료를 짧게 담고, with_facts 면 계산한 사실을 붙인다. 순수 함수."""
    turns = [f"{m.role}: {_text(m)[:HISTORY_CHARS]}" for m in request.history[-HISTORY_TURNS:]]
    state: dict[str, Any] = {
        "now": now.isoformat(timespec="minutes"),
        "recent_conversation": turns,
        "open_promises": request.open_loops,
        "external_events": request.external_events,
        "already_said_recently": request.recent_proactive,
    }
    if with_facts and request.facts:
        state["computed_facts"] = [fact.view() for fact in request.facts]
    return state


def candidate_items(request: ThoughtRequest, with_facts: bool, limit: int = MAX_ITEM_QUESTIONS) -> list[SituationFact]:
    """항목별 질문을 던질 후보. 사실이 있으면 처리 신호 없는 것, 30분 안이거나 지난 것, 시각 모름, 먼 것 순으로
    줄 세워 자른다.

    처리 신호나 먼 기한만으로 항목을 버리지는 않는다(정규식이 틀릴 수 있다). 순서와 상한으로만 줄인다. 순수 함수.
    """
    if with_facts and request.facts:
        return sorted(request.facts, key=_urgency)[:limit]
    texts = [*request.open_loops, *request.external_events]
    return [SituationFact(text=text) for text in texts[:limit]]


def gated_confidence(p: float, item_ps: list[float], with_facts: bool) -> float:
    """사실 모드에서는 전체 판단과 가장 높은 항목 판단 중 작은 쪽. 아니면 전체 판단 그대로. 순수 함수."""
    if with_facts and item_ps:
        return min(p, max(item_ps))
    return p


def _urgency(fact: SituationFact) -> tuple[int, int, int]:
    if fact.minutes is not None and fact.minutes <= 30:
        bucket = 0
    elif fact.minutes is None and fact.days is None:
        bucket = 1
    else:
        bucket = 2
    distance = abs(fact.minutes) if fact.minutes is not None else abs(fact.days or 0) * 1440
    return (fact.signal is not None, bucket, distance)


class DecisionGatedEngine(ThoughtEngine):
    """요청 사고는 그대로 두고, 성찰 사고는 decision model 을 먼저 묻는다.

    순서: 전체 판단 확률, (facts) 계산한 사실을 붙인 항목별 판단, 문턱 아래면 사고 LLM 을 부르지 않고 침묵,
    넘으면 확률이 가장 높은 항목을 앵커로 사고를 돌린다. 건넬 말이 비면 utterance_model 로 한두 문장을 만들고,
    (anchor) 말이 앵커 낱말을 하나도 담지 않으면 침묵한다. decision model 이 실패하면 안쪽 엔진의 프레임을 그대로 쓴다.
    """

    def __init__(
        self,
        inner: ThoughtEngine,
        decision: DecisionModel,
        utterance_model: ModelConfig,
        clock: Callable[[], datetime] | None = None,
        floor: float = UTTERANCE_FLOOR,
        persona: str = "",
        anchor: bool = True,
        facts: bool = True,
        max_item_questions: int = MAX_ITEM_QUESTIONS,
    ) -> None:
        self._inner = inner
        self._persona = persona
        self._floor = floor
        self._decision = decision
        self._utterance_model = utterance_model
        self._clock = clock or datetime.now
        self._anchor = anchor
        self._facts = facts
        self._max_items = max_item_questions

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        if request.mode != "reflection":
            return await self._inner.think(request)
        state = decision_state(request, self._clock(), with_facts=self._facts)
        p = await self._decision.yes_probability(state, SPEAK_QUESTION, SPEAK_NO, SPEAK_YES)
        if p is None:
            return await self._inner.think(request)
        tag = f"decision {self._decision.model} p={p:.2f}"
        if p < self._floor:
            # 사고 LLM 을 부르기 전에 끝낸다. 항목별 질문도 던지지 않는다
            logger.info(f"[Thought] proactive silent: {tag} < floor {self._floor:.2f}")
            return ThoughtFrame(decision="silent", confidence=p, rationale=f"[{tag}]")
        scored = await self._score_items(request, state) if (self._anchor or self._facts) else []
        confidence = gated_confidence(p, [ip for _, ip in scored], self._facts)
        anchor = max(scored, key=lambda pair: pair[1])[0].text if (self._anchor and scored) else ""
        if scored:
            tag += " items=" + ",".join(f"{ip:.2f}" for _, ip in scored)
        if confidence < self._floor:
            logger.info(f"[Thought] proactive silent: {tag} < floor {self._floor:.2f}")
            return ThoughtFrame(decision="silent", confidence=confidence, rationale=f"[{tag}]")
        frame = await self._inner.think(request.model_copy(update={"anchor": anchor}))
        if frame is None:
            return None
        utterance = frame.utterance
        if not utterance.strip():
            utterance = await self._utterance(state, anchor)
        if utterance.strip() and anchor and not anchor_present(anchor, utterance):
            # 근거 항목을 하나도 짚지 않은 말은 인사나 사용자 분석문, 방금 한 답의 재진술이었다
            logger.info(f"[Thought] proactive silent: anchor missing ({utterance[:60]})")
            utterance, tag = "", tag + " anchor missing"
        return frame.model_copy(
            update={
                # 안쪽 사고가 ask 로 정했으면 되묻는 성격을 남긴다
                "decision": (frame.decision if frame.decision in ("act", "ask") else "act")
                if utterance.strip()
                else "silent",
                "confidence": confidence,
                "utterance": utterance,
                "rationale": f"{frame.rationale} [{tag}]".strip(),
            }
        )

    async def _score_items(
        self, request: ThoughtRequest, state: dict[str, Any]
    ) -> list[tuple[SituationFact, float]]:
        """후보 항목마다 decision model 확률. 답하지 못한 항목은 뺀다."""
        items = candidate_items(request, self._facts, self._max_items)
        answers = await asyncio.gather(
            *(
                self._decision.yes_probability(
                    {**state, "focus_item": item.view() if self._facts else item.text},
                    ITEM_QUESTION,
                    ITEM_NO,
                    ITEM_YES,
                )
                for item in items
            )
        )
        return [(item, p) for item, p in zip(items, answers, strict=True) if p is not None]

    async def _utterance(self, state: dict[str, Any], anchor: str) -> str:
        prompt = UTTERANCE_PROMPT.format(
            anchor=ANCHOR_LINE.format(anchor=anchor) if anchor else "",
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
