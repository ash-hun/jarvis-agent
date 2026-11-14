"""ion 의 규칙: 관측 흐름에서 신호 여섯 가지를 가려내고, 같은 슬롯의 같은 신호는 같은 사고 id 다."""

import pytest
from datetime import datetime

from jarvis.ion.health_rules import AgentObservation, Observation, Signal, Thresholds, evaluate, incident_id

T = Thresholds()
NOON = datetime(2026, 11, 12, 12, 0)
NIGHT = datetime(2026, 11, 12, 23, 0)
SEC = 1000


def _obs(i: int, **kw: object) -> Observation:
    return Observation(at_ms=i * 15 * SEC, **kw)  # type: ignore[arg-type]


def _kinds(history: list[Observation], now: datetime = NOON) -> list[str]:
    return [s.kind for s in evaluate(history, T, now)]


def test_backend_down_needs_three_failures_in_a_row():
    assert _kinds([_obs(i, health_ok=False) for i in range(3)]) == ["backend_down"]
    assert _kinds([_obs(0, health_ok=False), _obs(1, health_ok=True), _obs(2, health_ok=False)]) == []


def test_restart_loop_counts_increase_inside_the_window_only():
    inside = [_obs(0, restart_count=1), _obs(1, restart_count=3), _obs(2, restart_count=4)]
    assert _kinds(inside) == ["restart_loop"]
    old = Observation(at_ms=0, restart_count=0)
    assert _kinds([old, Observation(at_ms=T.restart_loop_window_ms + 1, restart_count=3)]) == []


def test_loop_stall_and_memory_high_need_a_full_window():
    assert _kinds([_obs(0, loop_lag_ms=6000.0), _obs(1, loop_lag_ms=5000.0)]) == ["loop_stall"]
    assert _kinds([_obs(0, loop_lag_ms=6000.0), _obs(1, loop_lag_ms=10.0)]) == []
    hot = [Observation(at_ms=i * 60 * SEC, rss_bytes=90, memory_limit_bytes=100) for i in range(6)]
    assert _kinds(hot) == ["memory_high"]
    assert _kinds(hot[:5]) == []


def test_agent_signals_use_streak_and_stale_schedule_in_active_hours():
    agents = {"karen": AgentObservation(fail_streak=3, last_ok_ms=0, scheduled=True)}
    late = Observation(at_ms=T.stale_ms + 1, agents=agents)
    assert _kinds([late]) == ["agent_failing", "schedule_stale"]
    assert _kinds([late], now=NIGHT) == ["agent_failing"]
    ok = AgentObservation(fail_streak=2, last_ok_ms=0, scheduled=True)
    fresh = Observation(at_ms=T.stale_ms, agents={"karen": ok})
    assert _kinds([fresh]) == []


@pytest.mark.parametrize("history", [[], [Observation(at_ms=0)]])
def test_nothing_observed_means_no_signal(history):
    assert evaluate(history, T, NOON) == []


def test_incident_id_carries_the_opening_time_so_a_closed_one_never_blocks_a_new_one():
    signal = Signal("backend_down", "backend", "x")
    assert incident_id(signal, 1000) == "backend_down:backend:1000"
    assert incident_id(signal, 1000) != incident_id(signal, 2000)


def test_a_long_quiet_agent_is_not_an_incident():
    quiet = AgentObservation(last_active_ms=0, name="K.A.R.E.N.")
    # 관측 5761번째(86,415초)는 하루를 넘겼지만 침묵은 정상이라 신호가 없다
    assert evaluate([_obs(5761, agents={"karen": quiet})], Thresholds(), NOON) == []
