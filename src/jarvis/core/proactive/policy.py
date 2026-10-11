"""[core] proactive 게이팅 정책. 요청 시점 Dual-Channel 계획과 자율 발화의 말할지 말지를 판정한다."""

from __future__ import annotations

import time
from collections.abc import Callable

from jarvis.agent_layer.thought.types import ThoughtFrame
from jarvis.core.proactive.types import ProactiveDecision, ResponsePlan

# filler가 비었을 때 쓰는 대기-신호 fallback. 모두 "오래 걸림"을 명시한다.
DEFAULT_FILLERS = (
    "음… 잠시만요, 확인하고 말씀드릴게요.",
    "조금 시간이 걸릴 것 같아요. 알아보고 바로 알려드릴게요.",
    "잠깐만 기다려 주세요, 살펴보는 중이에요.",
)
# 먼저 건넨 말에 이만큼 답이 없으면 한 번만 약한 무시로 본다.
DEFAULT_IGNORE_AFTER_SEC = 600
# 게이팅 없는 기본 정책이 침묵할 때 남기는 판정 근거
SILENT_REASON = "proactivity disabled"


class ProactivityPolicy:
    """proactive 게이팅 전략의 기본 클래스. 교체 가능.

    두 판정을 제공한다:
    - plan_response : 요청 시점 Dual-Channel(즉시/지연) 계획
    - decide_proactive : daemon 자율 발화의 speak/silent 게이팅
    - check_awaiting / note_user_activity : 먼저 건넨 말에 답이 올 때까지 다시 말하지 않는 게이트
    기본 구현은 늘 즉시 응답하고 먼저 말하지 않는다(proactive 를 끈 것과 같다).
    """

    def plan_response(self, frame: ThoughtFrame) -> ResponsePlan:
        return ResponsePlan(mode="immediate")

    def check_awaiting(
        self, session_id: str = "default", now: float | None = None
    ) -> ProactiveDecision | None:
        return None

    def note_user_activity(self, session_id: str = "default") -> None:
        pass

    def decide_proactive(
        self, frame: ThoughtFrame, *, session_id: str = "default", now: float | None = None
    ) -> ProactiveDecision:
        return ProactiveDecision(speak=False, reason=SILENT_REASON)


class DefaultProactivityPolicy(ProactivityPolicy):
    """기본 게이팅. 응답 대기 + confidence 임계치 + 쿨다운 + 위험도 분리.

    순수 로직(설정·시계 주입)이라 단위 테스트가 쉽고, 호출부(core/daemon)와 분리된다.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.6,
        cooldown_sec: int = 300,
        filler_fallbacks: tuple[str, ...] = DEFAULT_FILLERS,
        clock: Callable[[], float] = time.monotonic,
        threshold_provider: Callable[[], float] | None = None,
        ignore_after_sec: int = DEFAULT_IGNORE_AFTER_SEC,
    ) -> None:
        self._threshold = confidence_threshold
        # 동적 임계치(피드백 학습, C3). 없으면 고정 confidence_threshold 사용.
        self._threshold_provider = threshold_provider
        self._cooldown = cooldown_sec
        self._fillers = filler_fallbacks or DEFAULT_FILLERS
        self._clock = clock
        self._last_spoke: dict[str, float] = {}
        self._ignore_after = ignore_after_sec
        # 세션별 "답을 기다리는 발화" 시각과 무시로 이미 셌는지. 사용자가 무엇이든 보내면 지운다.
        # ponytail: 메모리에만 있어 재시작하면 게이트가 풀린다, 재시작 뒤 재발화가 문제면 세션 저장소로
        self._awaiting: dict[str, tuple[float, bool]] = {}
        self._filler_idx = 0

    def _current_threshold(self) -> float:
        return self._threshold_provider() if self._threshold_provider else self._threshold

    # ── 요청-기반 Dual-Channel ──────────────────────────────────────────────────

    def plan_response(self, frame: ThoughtFrame) -> ResponsePlan:
        if not frame.needs_background:
            return ResponsePlan(mode="immediate")
        # filler는 항상 비어있지 않게 보장. 사용자에게 "오래 걸림"을 반드시 전달.
        filler = frame.filler.strip() or self._next_fallback()
        return ResponsePlan(mode="deferred", filler=filler)

    # ── 응답 대기 게이트 ────────────────────────────────────────────────────────

    def check_awaiting(
        self, session_id: str = "default", now: float | None = None
    ) -> ProactiveDecision | None:
        """답을 기다리는 발화가 있으면 침묵 판정, 없으면 None.

        답 없이 ignore_after_sec 가 지나면 그 발화에 대해 딱 한 번 ignored=True 를 돌려준다.
        """
        pending = self._awaiting.get(session_id)
        if pending is None:
            return None
        spoke_at, counted = pending
        t = self._clock() if now is None else now
        ignored = not counted and (t - spoke_at) >= self._ignore_after
        if ignored:
            self._awaiting[session_id] = (spoke_at, True)
        return ProactiveDecision(speak=False, reason="awaiting reply", ignored=ignored)

    def note_user_activity(self, session_id: str = "default") -> None:
        """사용자가 메시지나 피드백을 보냈다. 다시 먼저 말할 수 있다. 몇 번 불러도 같다."""
        self._awaiting.pop(session_id, None)

    # ── daemon 자율 발화 게이팅 ────────────────────────────────────────────────

    def decide_proactive(
        self, frame: ThoughtFrame, *, session_id: str = "default", now: float | None = None
    ) -> ProactiveDecision:
        t = self._clock() if now is None else now
        awaiting = self.check_awaiting(session_id, now=t)
        if awaiting is not None:
            return awaiting
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

        last = self._last_spoke.get(session_id)
        if last is not None and (t - last) < self._cooldown:
            return ProactiveDecision(speak=False, reason="cooldown")
        self._last_spoke[session_id] = t
        self._awaiting[session_id] = (t, False)

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
