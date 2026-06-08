"""Proactive 코어(Tier 1 B1) 단위 테스트 — 정책 게이팅 + Dual-Channel."""

from __future__ import annotations

import pytest

from jarvis.agent_layer.thought.types import ProactiveAction, ThoughtFrame
from jarvis.core.proactive import (
    DefaultProactivityCore,
    DefaultProactivityPolicy,
    ProactiveMessage,
    ProactivityCore,
    ProactivityPolicy,
)


class _Clock:
    """주입식 단조 시계 — 쿨다운 경계 테스트용."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# ── B1 정책: plan_response (Dual-Channel 트리거) ──────────────────────────────


def test_plan_immediate_when_no_background():
    policy = DefaultProactivityPolicy()
    plan = policy.plan_response(ThoughtFrame(needs_background=False))
    assert plan.mode == "immediate"
    assert plan.filler == ""


def test_plan_deferred_uses_frame_filler():
    policy = DefaultProactivityPolicy()
    frame = ThoughtFrame(needs_background=True, filler="배포 로그 보고 올게요, 잠시만요")
    plan = policy.plan_response(frame)
    assert plan.mode == "deferred"
    assert plan.filler == "배포 로그 보고 올게요, 잠시만요"


def test_plan_deferred_falls_back_when_filler_empty():
    policy = DefaultProactivityPolicy()
    # needs_background인데 filler가 비면 대기-신호 fallback으로 반드시 채운다.
    plan = policy.plan_response(ThoughtFrame(needs_background=True, filler="   "))
    assert plan.mode == "deferred"
    assert plan.filler  # 비어있지 않음


def test_fallback_fillers_rotate():
    policy = DefaultProactivityPolicy()
    seen = {policy.plan_response(ThoughtFrame(needs_background=True)).filler for _ in range(3)}
    assert len(seen) >= 2  # 변화를 준다


# ── B1 정책: decide_proactive (daemon 게이팅) ─────────────────────────────────


def test_silent_decision_is_suppressed():
    policy = DefaultProactivityPolicy()
    d = policy.decide_proactive(ThoughtFrame(decision="silent", confidence=0.9))
    assert d.speak is False
    assert "silent" in d.reason


def test_below_threshold_suppressed():
    policy = DefaultProactivityPolicy(confidence_threshold=0.6)
    d = policy.decide_proactive(ThoughtFrame(decision="ask", confidence=0.4))
    assert d.speak is False
    assert "confidence" in d.reason


def test_gated_pass_speaks_and_splits_risk():
    policy = DefaultProactivityPolicy(confidence_threshold=0.6)
    frame = ThoughtFrame(
        decision="act",
        confidence=0.8,
        interpretation="배포 상태가 궁금한 듯",
        proactive_actions=[
            ProactiveAction(kind="tool", description="로그 읽기", risk="low"),
            ProactiveAction(kind="tool", description="재배포", risk="high"),
        ],
    )
    d = policy.decide_proactive(frame)
    assert d.speak is True
    assert d.message == "배포 상태가 궁금한 듯"
    assert len(d.autonomous_actions) == 1 and d.autonomous_actions[0].risk == "low"
    assert len(d.approval_actions) == 1 and d.approval_actions[0].risk == "high"


def test_cooldown_blocks_second_speak():
    clock = _Clock()
    policy = DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=300, clock=clock)
    frame = ThoughtFrame(decision="ask", confidence=0.9, interpretation="x")

    first = policy.decide_proactive(frame, session_id="s1")
    assert first.speak is True

    clock.t += 100  # 쿨다운 이내
    second = policy.decide_proactive(frame, session_id="s1")
    assert second.speak is False and second.reason == "cooldown"

    clock.t += 250  # 쿨다운 경과(누적 350s > 300)
    third = policy.decide_proactive(frame, session_id="s1")
    assert third.speak is True


def test_cooldown_is_per_session():
    clock = _Clock()
    policy = DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=300, clock=clock)
    frame = ThoughtFrame(decision="ask", confidence=0.9, interpretation="x")
    assert policy.decide_proactive(frame, session_id="a").speak is True
    # 다른 세션은 독립적으로 발화 가능.
    assert policy.decide_proactive(frame, session_id="b").speak is True


# ── ProactivityCore: Dual-Channel dispatch ────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_immediate_runs_main_synchronously():
    emitted: list[ProactiveMessage] = []
    core = DefaultProactivityCore(emit_proactive=lambda m: _collect(emitted, m))

    ran = {"v": False}

    async def run_main():
        ran["v"] = True
        return None

    await core.dispatch_request(ThoughtFrame(needs_background=False), run_main)
    assert ran["v"] is True
    assert emitted == []  # filler 없음


@pytest.mark.asyncio
async def test_dispatch_none_frame_runs_main():
    emitted: list[ProactiveMessage] = []
    core = DefaultProactivityCore(emit_proactive=lambda m: _collect(emitted, m))
    ran = {"v": False}

    async def run_main():
        ran["v"] = True
        return None

    await core.dispatch_request(None, run_main)
    assert ran["v"] is True
    assert emitted == []


@pytest.mark.asyncio
async def test_dispatch_deferred_emits_filler_then_backgrounds():
    emitted: list[ProactiveMessage] = []
    spawned: list = []

    def spawn(coro):
        # 즉시 실행하지 않고 보관 — filler가 메인보다 먼저 나갔는지 검증.
        spawned.append(coro)

    core = DefaultProactivityCore(emit_proactive=lambda m: _collect(emitted, m), spawn=spawn)
    ran = {"v": False}

    async def run_main():
        ran["v"] = True
        return None

    frame = ThoughtFrame(needs_background=True, filler="확인하고 올게요, 잠시만요")
    result = await core.dispatch_request(frame, run_main)

    # 반환 시점: filler는 이미 나갔고, 메인은 아직 실행 전(백그라운드 예약만).
    assert result is None
    assert len(emitted) == 1
    assert emitted[0].kind == "filler"
    assert emitted[0].text == "확인하고 올게요, 잠시만요"
    assert ran["v"] is False
    assert len(spawned) == 1

    # 백그라운드 실행 시 메인이 돈다.
    await spawned[0]
    assert ran["v"] is True


@pytest.mark.asyncio
async def test_reflect_pushes_when_gated_pass():
    emitted: list[ProactiveMessage] = []
    core = DefaultProactivityCore(
        emit_proactive=lambda m: _collect(emitted, m),
        policy=DefaultProactivityPolicy(confidence_threshold=0.5),
    )
    frame = ThoughtFrame(decision="ask", confidence=0.9, interpretation="먼저 알려줄 것")

    decision = await core.reflect(frame, session_id="s1")
    assert decision.speak is True
    assert len(emitted) == 1
    assert emitted[0].kind == "proactive"
    assert emitted[0].text == "먼저 알려줄 것"


@pytest.mark.asyncio
async def test_reflect_silent_does_not_push():
    emitted: list[ProactiveMessage] = []
    core = DefaultProactivityCore(emit_proactive=lambda m: _collect(emitted, m))
    decision = await core.reflect(ThoughtFrame(decision="silent"), session_id="s1")
    assert decision.speak is False
    assert emitted == []


def test_default_core_satisfies_protocol():
    core = DefaultProactivityCore(emit_proactive=lambda m: _noop())
    assert isinstance(core, ProactivityCore)


def test_default_policy_satisfies_protocol():
    assert isinstance(DefaultProactivityPolicy(), ProactivityPolicy)


async def _collect(bucket: list, msg: ProactiveMessage) -> None:
    bucket.append(msg)


async def _noop() -> None:
    return None
