"""Proactive 코어(Tier 1 B1) 단위 테스트 — 정책 게이팅 + Dual-Channel."""

import pytest

from jarvis.core.proactive import (
    DefaultProactivityCore,
    DefaultProactivityPolicy,
    ProactiveMessage,
    ProactivityCore,
    ProactivityPolicy,
)
from jarvis.agent_layer.thought.types import ProactiveAction, ThoughtFrame


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
        utterance="배포 상태가 궁금한 듯",
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
    frame = ThoughtFrame(decision="ask", confidence=0.9, utterance="x")

    first = policy.decide_proactive(frame, session_id="s1")
    assert first.speak is True
    policy.note_user_activity("s1")  # 답이 왔다고 두고 쿨다운만 본다

    clock.t += 100  # 쿨다운 이내
    second = policy.decide_proactive(frame, session_id="s1")
    assert second.speak is False and second.reason == "cooldown"

    clock.t += 250  # 쿨다운 경과(누적 350s > 300)
    third = policy.decide_proactive(frame, session_id="s1")
    assert third.speak is True


def test_cooldown_is_per_session():
    clock = _Clock()
    policy = DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=300, clock=clock)
    frame = ThoughtFrame(decision="ask", confidence=0.9, utterance="x")
    assert policy.decide_proactive(frame, session_id="a").speak is True
    # 다른 세션은 독립적으로 발화 가능.
    assert policy.decide_proactive(frame, session_id="b").speak is True


def test_empty_utterance_is_silent_and_does_not_consume_cooldown():
    clock = _Clock()
    policy = DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=300, clock=clock)
    # 분석문(interpretation)만 있고 건넬 말이 없으면 침묵한다. 분석문을 대신 내보내지 않는다.
    muted = policy.decide_proactive(
        ThoughtFrame(decision="act", confidence=0.9, interpretation="사용자는 불안해 보인다", rationale="r"),
        session_id="s1",
    )
    assert muted.speak is False and muted.reason == "empty utterance"
    # 침묵은 쿨다운을 소비하지 않는다.
    spoken = policy.decide_proactive(
        ThoughtFrame(decision="act", confidence=0.9, utterance="배포 결과 공유 잊지 마세요"), session_id="s1"
    )
    assert spoken.speak is True and spoken.message == "배포 결과 공유 잊지 마세요"


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
    frame = ThoughtFrame(decision="ask", confidence=0.9, utterance="먼저 알려줄 것")

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


@pytest.mark.asyncio
async def test_reflect_executes_autonomous_and_augments_message():
    from jarvis.agent_layer.thought.types import ProactiveAction

    emitted: list[ProactiveMessage] = []
    seen: dict = {}

    async def execute(actions):
        seen["actions"] = actions
        return "(미리 해둠) · 로그 읽기"

    core = DefaultProactivityCore(
        emit_proactive=lambda m: _collect(emitted, m),
        policy=DefaultProactivityPolicy(confidence_threshold=0.5),
    )
    frame = ThoughtFrame(
        decision="act",
        confidence=0.9,
        utterance="배포 상태 확인이 필요해 보임",
        proactive_actions=[ProactiveAction(kind="tool", description="로그 읽기", risk="low")],
    )
    decision = await core.reflect(frame, session_id="s1", execute=execute)

    assert decision.speak is True
    assert len(seen["actions"]) == 1  # low-risk만 전달
    assert len(emitted) == 1
    assert "배포 상태" in emitted[0].text and "미리 해둠" in emitted[0].text


@pytest.mark.asyncio
async def test_reflect_execute_failure_falls_back_to_message():
    emitted: list[ProactiveMessage] = []

    async def boom(actions):
        raise RuntimeError("exec down")

    core = DefaultProactivityCore(
        emit_proactive=lambda m: _collect(emitted, m),
        policy=DefaultProactivityPolicy(confidence_threshold=0.5),
    )
    frame = ThoughtFrame(decision="ask", confidence=0.9, utterance="알림")
    decision = await core.reflect(frame, session_id="s1", execute=boom)

    # 실행이 터져도 메시지는 나간다.
    assert decision.speak is True
    assert emitted[0].text == "알림"


def test_default_core_satisfies_protocol():
    core = DefaultProactivityCore(emit_proactive=lambda m: _noop())
    assert isinstance(core, ProactivityCore)


def test_default_policy_satisfies_protocol():
    assert isinstance(DefaultProactivityPolicy(), ProactivityPolicy)


# ── ProactivityDaemon (B3) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daemon_tick_invokes_all_targets():
    from jarvis.core.proactive import ProactivityDaemon

    calls = {"a": 0, "b": 0}

    async def ra():
        calls["a"] += 1

    async def rb():
        calls["b"] += 1

    daemon = ProactivityDaemon(lambda: [ra, rb], interval_sec=0)
    await daemon.tick()
    assert calls == {"a": 1, "b": 1}  # 멀티세션 — 모든 대상 성찰


@pytest.mark.asyncio
async def test_daemon_targets_reevaluated_each_tick():
    from jarvis.core.proactive import ProactivityDaemon

    calls = {"n": 0}

    async def reflect():
        calls["n"] += 1

    # 처음엔 대상 0개, 다음 틱엔 1개 — provider 재평가로 추종.
    state = {"targets": []}
    daemon = ProactivityDaemon(lambda: state["targets"], interval_sec=0)
    await daemon.tick()
    assert calls["n"] == 0
    state["targets"] = [reflect]
    await daemon.tick()
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_daemon_tick_isolates_target_failure():
    from jarvis.core.proactive import ProactivityDaemon

    calls = {"ok": 0}

    async def boom():
        raise RuntimeError("reflect down")

    async def ok():
        calls["ok"] += 1

    # 한 대상이 터져도 나머지는 성찰된다.
    daemon = ProactivityDaemon(lambda: [boom, ok], interval_sec=0)
    await daemon.tick()
    assert calls["ok"] == 1


@pytest.mark.asyncio
async def test_daemon_loop_runs_ticks_then_stops():
    import asyncio

    from jarvis.core.proactive import ProactivityDaemon

    calls = {"n": 0}
    stop_evt = asyncio.Event()

    async def reflect():
        calls["n"] += 1

    async def fake_sleep(_):
        # 2틱 후, 멈출 때까지 길게 대기(취소로 빠져나옴).
        if calls["n"] >= 2:
            stop_evt.set()
            await asyncio.sleep(3600)

    daemon = ProactivityDaemon(lambda: [reflect], interval_sec=0, sleep=fake_sleep)
    await daemon.start()
    assert daemon.is_running is True
    await asyncio.wait_for(stop_evt.wait(), timeout=1.0)
    await daemon.stop()

    assert calls["n"] == 2
    assert daemon.is_running is False


@pytest.mark.asyncio
async def test_daemon_start_is_idempotent():
    from jarvis.core.proactive import ProactivityDaemon

    async def reflect():
        return None

    async def never(_):
        import asyncio

        await asyncio.sleep(3600)

    daemon = ProactivityDaemon(lambda: [reflect], interval_sec=0, sleep=never)
    await daemon.start()
    first = daemon._task
    await daemon.start()  # 두 번째 start는 무시(중복 task 금지)
    assert daemon._task is first
    await daemon.stop()


async def _collect(bucket: list, msg: ProactiveMessage) -> None:
    bucket.append(msg)


async def _noop() -> None:
    return None


# ── 응답 대기 게이트 ──────────────────────────────────────────────────────────


def test_awaiting_reply_blocks_even_after_cooldown():
    clock = _Clock()
    policy = DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=300, clock=clock)
    frame = ThoughtFrame(decision="ask", confidence=0.95, utterance="x")
    assert policy.check_awaiting("s1") is None
    assert policy.decide_proactive(frame, session_id="s1").speak is True

    clock.t += 3600  # 쿨다운은 한참 지났지만 답이 없다
    blocked = policy.decide_proactive(frame, session_id="s1")
    assert blocked.speak is False and blocked.reason == "awaiting reply"
    # 다른 세션은 막지 않는다
    assert policy.decide_proactive(frame, session_id="s2").speak is True


def test_user_activity_releases_gate_and_is_idempotent():
    clock = _Clock()
    policy = DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0, clock=clock)
    frame = ThoughtFrame(decision="ask", confidence=0.95, utterance="x")
    policy.decide_proactive(frame, session_id="s1")
    policy.note_user_activity("s1")
    policy.note_user_activity("s1")
    policy.note_user_activity("never-spoke")
    assert policy.check_awaiting("s1") is None
    assert policy.decide_proactive(frame, session_id="s1").speak is True


def test_ignored_reported_once_after_ignore_window():
    clock = _Clock()
    policy = DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0, ignore_after_sec=600, clock=clock)
    frame = ThoughtFrame(decision="ask", confidence=0.95, utterance="x")
    policy.decide_proactive(frame, session_id="s1")

    clock.t += 300
    assert policy.check_awaiting("s1").ignored is False
    clock.t += 300
    assert policy.check_awaiting("s1").ignored is True
    clock.t += 300
    assert policy.check_awaiting("s1").ignored is False  # 같은 발화는 한 번만 센다

    # 답 뒤 새 발화는 다시 셀 수 있다
    policy.note_user_activity("s1")
    policy.decide_proactive(frame, session_id="s1")
    clock.t += 600
    assert policy.check_awaiting("s1").ignored is True
