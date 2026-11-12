"""[ion] 관측값의 흐름에서 사고 신호를 가려내는 순수 규칙. 임계치와 창은 인자로 받는다."""

from typing import Literal
from datetime import datetime
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence

SignalKind = Literal["backend_down", "restart_loop", "loop_stall", "memory_high", "agent_failing", "schedule_stale"]
BACKEND = "backend"
# 사고 id 의 시각 자리. 같은 신호가 한 시간 안에 다시 나면 같은 사고다
SLOT_MS = 3_600_000


@dataclass(frozen=True)
class AgentObservation:
    """에이전트 하나의 작업 상태. scheduled 는 그 에이전트에 켜진 스케줄 작업이 있는지다."""

    fail_streak: int = 0
    last_ok_ms: int | None = None
    scheduled: bool = False


@dataclass(frozen=True)
class Observation:
    """감시 루프 한 바퀴의 관측값. 못 잰 값은 None 이고 규칙은 그 값을 건너뛴다."""

    at_ms: int
    health_ok: bool | None = None
    restart_count: int | None = None
    loop_lag_ms: float | None = None
    rss_bytes: int | None = None
    memory_limit_bytes: int | None = None
    agents: Mapping[str, AgentObservation] = field(default_factory=dict)


@dataclass(frozen=True)
class Thresholds:
    """기본값은 docs/ion-plan.md 의 표다."""

    health_fail_count: int = 3
    restart_loop_count: int = 3
    restart_loop_window_ms: int = 600_000
    loop_lag_ms: float = 5_000.0
    loop_lag_count: int = 2
    memory_ratio: float = 0.85
    memory_window_ms: int = 300_000
    fail_streak: int = 3
    stale_ms: int = 7_200_000
    active_hours: tuple[int, int] = (9, 21)


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    target: str
    detail: str


def evaluate(history: Sequence[Observation], t: Thresholds, now: datetime) -> list[Signal]:
    """최근 관측(오래된 것부터)에서 지금 켜진 신호. 같은 입력이면 같은 출력이다."""
    if not history:
        return []
    latest = history[-1]
    signals: list[Signal] = []
    if _last_n(history, t.health_fail_count, lambda o: o.health_ok, False):
        signals.append(Signal("backend_down", BACKEND, f"health 실패 {t.health_fail_count}회 연속"))
    restarts = _restarts_in_window(history, t.restart_loop_window_ms)
    if restarts >= t.restart_loop_count:
        minutes = t.restart_loop_window_ms // 60_000
        signals.append(Signal("restart_loop", BACKEND, f"{minutes}분 안 재시작 {restarts}회"))
    stalled = _last_n(history, t.loop_lag_count, lambda o: (o.loop_lag_ms or 0.0) >= t.loop_lag_ms, True)
    if stalled:
        signals.append(Signal("loop_stall", BACKEND, f"이벤트 루프 지연 {latest.loop_lag_ms:.0f}ms"))
    if _memory_high_for(history, t):
        ratio = (latest.rss_bytes or 0) / (latest.memory_limit_bytes or 1)
        signals.append(Signal("memory_high", BACKEND, f"메모리 {ratio:.0%}"))
    for agent, obs in sorted(latest.agents.items()):
        if obs.fail_streak >= t.fail_streak:
            signals.append(Signal("agent_failing", agent, f"연속 실패 {obs.fail_streak}회"))
        if obs.scheduled and _active(now, t.active_hours) and _stale(obs, latest.at_ms, t.stale_ms):
            signals.append(Signal("schedule_stale", agent, f"{t.stale_ms // 3_600_000}시간 넘게 성공한 차례 없음"))
    return signals


def incident_id(signal: Signal, at_ms: int, slot_ms: int = SLOT_MS) -> str:
    """`종류:대상:시각 슬롯`. 같은 슬롯의 같은 신호는 같은 사고다. 순수 함수."""
    return f"{signal.kind}:{signal.target}:{at_ms // slot_ms}"


def _last_n(history: Sequence[Observation], n: int, pick: object, expected: object) -> bool:
    """마지막 n 개 관측이 모두 expected 인가. 표본이 n 개보다 적으면 False."""
    if len(history) < n or n <= 0:
        return False
    assert callable(pick)
    return all(pick(o) == expected for o in history[-n:])


def _restarts_in_window(history: Sequence[Observation], window_ms: int) -> int:
    """창 안에서 늘어난 재시작 횟수. Docker 의 RestartCount 는 단조 증가라 처음과 끝의 차다."""
    latest = history[-1]
    if latest.restart_count is None:
        return 0
    counts = [o.restart_count for o in history if o.restart_count is not None and latest.at_ms - o.at_ms <= window_ms]
    return latest.restart_count - counts[0] if counts else 0


def _memory_high_for(history: Sequence[Observation], t: Thresholds) -> bool:
    """창 안 관측이 모두 임계 비율 이상이고 창을 다 채웠는가."""
    latest = history[-1]
    inside = [o for o in history if latest.at_ms - o.at_ms <= t.memory_window_ms]
    if not inside or latest.at_ms - inside[0].at_ms < t.memory_window_ms:
        return False
    return all(
        o.rss_bytes is not None and o.memory_limit_bytes and o.rss_bytes / o.memory_limit_bytes >= t.memory_ratio
        for o in inside
    )


def _active(now: datetime, hours: tuple[int, int]) -> bool:
    return hours[0] <= now.hour <= hours[1]


def _stale(obs: AgentObservation, at_ms: int, stale_ms: int) -> bool:
    return obs.last_ok_ms is not None and at_ms - obs.last_ok_ms > stale_ms
