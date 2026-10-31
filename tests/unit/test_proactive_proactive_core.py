"""proactive: 코어가 메인을 바로 또는 filler 뒤 백그라운드로 돌리고 성찰 결과를 push 하는지 검증한다."""

import pytest

from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy, ProactiveMessage, ProactivityCore
from jarvis.agent_layer.thought.thought_types import ProactiveAction, ThoughtFrame


def _core(emitted: list[ProactiveMessage], **kw) -> DefaultProactivityCore:
    async def emit(message: ProactiveMessage) -> None:
        emitted.append(message)

    return DefaultProactivityCore(emit_proactive=emit, **kw)


def _gated(emitted: list[ProactiveMessage]) -> DefaultProactivityCore:
    return _core(emitted, policy=DefaultProactivityPolicy(confidence_threshold=0.5))


def test_default_core_satisfies_protocol():
    assert isinstance(_core([]), ProactivityCore)


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", [ThoughtFrame(needs_background=False), None])
async def test_dispatch_request_runs_main_inline_without_filler(frame):
    emitted: list[ProactiveMessage] = []
    ran = {"v": False}

    async def run_main():
        ran["v"] = True

    await _core(emitted).dispatch_request(frame, run_main)

    assert ran["v"] is True
    assert emitted == []


@pytest.mark.asyncio
async def test_dispatch_request_deferred_emits_filler_before_background_main():
    emitted: list[ProactiveMessage] = []
    spawned: list = []
    ran = {"v": False}

    async def run_main():
        ran["v"] = True

    core = _core(emitted, spawn=spawned.append)
    frame = ThoughtFrame(needs_background=True, filler="확인하고 올게요, 잠시만요")

    result = await core.dispatch_request(frame, run_main)

    assert result is None
    assert [(m.kind, m.text) for m in emitted] == [("filler", "확인하고 올게요, 잠시만요")]
    assert ran["v"] is False and len(spawned) == 1
    await spawned[0]
    assert ran["v"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("frame", "speak", "pushed"),
    [
        (ThoughtFrame(decision="ask", confidence=0.9, utterance="알려줄 것"), True, [("proactive", "알려줄 것")]),
        (ThoughtFrame(decision="silent"), False, []),
    ],
)
async def test_reflect_pushes_only_when_gated_pass(frame, speak, pushed):
    emitted: list[ProactiveMessage] = []

    decision = await _gated(emitted).reflect(frame, session_id="s1")

    assert decision.speak is speak
    assert [(m.kind, m.text) for m in emitted] == pushed


@pytest.mark.asyncio
async def test_reflect_executes_low_risk_actions_and_appends_summary():
    emitted: list[ProactiveMessage] = []
    seen: dict = {}

    async def execute(actions):
        seen["actions"] = actions
        return "(미리 해둠) · 로그 읽기"

    frame = ThoughtFrame(
        decision="act",
        confidence=0.9,
        utterance="배포 상태 확인이 필요해 보임",
        proactive_actions=[ProactiveAction(kind="tool", description="로그 읽기", risk="low")],
    )

    decision = await _gated(emitted).reflect(frame, session_id="s1", execute=execute)

    assert decision.speak is True
    assert len(seen["actions"]) == 1
    assert len(emitted) == 1
    assert "배포 상태" in emitted[0].text and "미리 해둠" in emitted[0].text


@pytest.mark.asyncio
async def test_reflect_still_pushes_message_when_execute_fails():
    emitted: list[ProactiveMessage] = []

    async def boom(actions):
        raise RuntimeError("exec down")

    frame = ThoughtFrame(decision="ask", confidence=0.9, utterance="알림")

    decision = await _gated(emitted).reflect(frame, session_id="s1", execute=boom)

    assert decision.speak is True
    assert emitted[0].text == "알림"


SPEAKING_FRAME = ThoughtFrame(decision="act", confidence=1.0, utterance="먼저 말할 거리")


async def test_core_default_runs_main_and_stays_silent():
    core = ProactivityCore()
    calls: list[str] = []

    async def run_main():  # type: ignore[no-untyped-def]
        calls.append("main")
        return None

    assert await core.dispatch_request(ThoughtFrame(needs_background=True), run_main) is None
    assert calls == ["main"]
    decision = await core.reflect(SPEAKING_FRAME, session_id="s")
    assert decision.speak is False
    assert core.check_awaiting("s") is None
    core.note_user_activity("s")
