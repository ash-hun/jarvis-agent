from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from jarvis.agent_layer.thought.types import ThoughtFrame
from jarvis.core.proactive.types import ProactiveDecision, ResponsePlan

# filler가 비었을 때 쓰는 대기-신호 fallback. 모두 "오래 걸림"을 명시한다.
DEFAULT_FILLERS = (
    "음… 잠시만요, 확인하고 말씀드릴게요.",
    "조금 시간이 걸릴 것 같아요. 알아보고 바로 알려드릴게요.",
    "잠깐만 기다려 주세요, 살펴보는 중이에요.",
)


@runtime_checkable
class ProactivityPolicy(Protocol):
    """proactive 게이팅 전략 — 교체 가능.

    두 판정을 제공한다:
    - plan_response : 요청 시점 Dual-Channel(즉시/지연) 계획
    - decide_proactive : daemon 자율 발화의 speak/silent 게이팅
    """

    def plan_response(self, frame: ThoughtFrame) -> ResponsePlan: ...

    def decide_proactive(
        self, frame: ThoughtFrame, *, session_id: str = "default", now: float | None = None
    ) -> ProactiveDecision: ...


class DefaultProactivityPolicy:
    """기본 게이팅 — confidence 임계치 + 쿨다운 + 위험도 분리.

    순수 로직(설정·시계 주입)이라 단위 테스트가 쉽고, 호출부(core/daemon)와 분리된다.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.6,
        cooldown_sec: int = 300,
        filler_fallbacks: tuple[str, ...] = DEFAULT_FILLERS,
        clock: Callable[[], float] = time.monotonic,
        threshold_provider: Callable[[], float] | None = None,
    ) -> None:
        self._threshold = confidence_threshold
        # 동적 임계치(피드백 학습, C3). 없으면 고정 confidence_threshold 사용.
        self._threshold_provider = threshold_provider
        self._cooldown = cooldown_sec
        self._fillers = filler_fallbacks or DEFAULT_FILLERS
        self._clock = clock
        self._last_spoke: dict[str, float] = {}
        self._filler_idx = 0

    def _current_threshold(self) -> float:
        return self._threshold_provider() if self._threshold_provider else self._threshold

    # ── 요청-기반 Dual-Channel ──────────────────────────────────────────────────

    def plan_response(self, frame: ThoughtFrame) -> ResponsePlan:
        if not frame.needs_background:
            return ResponsePlan(mode="immediate")
        # filler는 항상 비어있지 않게 보장 — 사용자에게 "오래 걸림"을 반드시 전달.
        filler = frame.filler.strip() or self._next_fallback()
        return ResponsePlan(mode="deferred", filler=filler)

    # ── daemon 자율 발화 게이팅 ────────────────────────────────────────────────

    def decide_proactive(
        self, frame: ThoughtFrame, *, session_id: str = "default", now: float | None = None
    ) -> ProactiveDecision:
        if frame.decision not in ("act", "ask"):
            return ProactiveDecision(speak=False, reason=f"decision={frame.decision}")
        threshold = self._current_threshold()
        if frame.confidence < threshold:
            return ProactiveDecision(
                speak=False,
                reason=f"confidence {frame.confidence:.2f} < {threshold:.2f}",
            )

        # 건넬 말이 없으면 침묵. interpretation 으로 대체하면 사용자 분석문이 그대로 나간다.
        utterance = frame.utterance.strip()
        if not utterance:
            return ProactiveDecision(speak=False, reason="empty utterance")

        t = self._clock() if now is None else now
        last = self._last_spoke.get(session_id)
        if last is not None and (t - last) < self._cooldown:
            return ProactiveDecision(speak=False, reason="cooldown")
        self._last_spoke[session_id] = t

        low = [a for a in frame.proactive_actions if a.risk == "low"]
        high = [a for a in frame.proactive_actions if a.risk == "high"]
        return ProactiveDecision(
            speak=True,
            message=utterance,
            reason="gated-pass",
            autonomous_actions=low,
            approval_actions=high,
        )

    def _next_fallback(self) -> str:
        filler = self._fillers[self._filler_idx % len(self._fillers)]
        self._filler_idx += 1
        return filler
