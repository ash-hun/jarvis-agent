"""Proactive 배선 — session.prompt의 Dual-Channel(스텝 4) 통합."""

import pytest
import asyncio

from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy
from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.types import ProactiveMessageEvent


class StubEngine:
    def __init__(self, frame: ThoughtFrame | None) -> None:
        self._frame = frame

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        return self._frame


def _build_session(fx, engine=None, proactivity_factory=None, feedback_learner=None):
    from jarvis.core.session import AgentSession

    return AgentSession(
        model=fx["model"],
        session_id="test-session",
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
        thought_engine=engine,
        proactivity_factory=proactivity_factory,
        feedback_learner=feedback_learner,
    )


def _factory(emit):
    return DefaultProactivityCore(emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5))


@pytest.fixture
def fx(
    faux_model,
    permissive_pipeline,
    plugin_runner,
    session_memory,
    tool_registry,
    skill_registry,
    jsonl_repo,
):
    return {
        "model": faux_model,
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }


@pytest.mark.asyncio
async def test_immediate_frame_runs_synchronously(fx):
    await fx["repo"].create(session_id="test-session")
    engine = StubEngine(ThoughtFrame(needs_background=False, interpretation="x"))
    session = _build_session(fx, engine=engine, proactivity_factory=_factory)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    result = await session.prompt("간단한 질문")

    # 즉시 모드 — 메인 응답이 동기로 반환되고 filler 이벤트 없음.
    assert result is not None
    assert not [e for e in events if isinstance(e, ProactiveMessageEvent)]


@pytest.mark.asyncio
async def test_deferred_frame_emits_filler_then_backgrounds(fx):
    await fx["repo"].create(session_id="test-session")
    engine = StubEngine(ThoughtFrame(needs_background=True, filler="잠깐만요, 확인하고 알려드릴게요"))
    session = _build_session(fx, engine=engine, proactivity_factory=_factory)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    result = await session.prompt("오래 걸리는 작업")

    # deferred — filler가 즉시 나가고 메인은 백그라운드(반환 None).
    fillers = [e for e in events if isinstance(e, ProactiveMessageEvent) and e.kind == "filler"]
    assert len(fillers) == 1
    assert fillers[0].text == "잠깐만요, 확인하고 알려드릴게요"
    assert result is None

    # 백그라운드 메인 루프가 완료될 때까지 잠시 양보.
    await asyncio.sleep(0.05)
    # 끝난 답은 화면 스트림과 별개로 answer 로 한 번 더 나간다(자리를 뜬 사람에게 닿는 외부 채널용)
    answers = [e for e in events if isinstance(e, ProactiveMessageEvent) and e.kind == "answer"]
    history = await fx["repo"].get_messages("test-session")
    assert [a.text for a in answers] == [history[-1].text().strip()]


@pytest.mark.asyncio
async def test_no_proactivity_factory_is_noop(fx):
    await fx["repo"].create(session_id="test-session")
    engine = StubEngine(ThoughtFrame(needs_background=True, filler="무시됨"))
    session = _build_session(fx, engine=engine, proactivity_factory=None)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    result = await session.prompt("질문")
    # proactivity 없으면 needs_background여도 Dual-Channel 미적용 → 동기 실행.
    assert result is not None
    assert not [e for e in events if isinstance(e, ProactiveMessageEvent)]


# ── session.reflect (B3 daemon이 호출) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_reflect_pushes_proactive_when_gated(fx):
    await fx["repo"].create(session_id="test-session")
    # decision=ask + 높은 confidence → 게이팅 통과 → proactive push.
    engine = StubEngine(
        ThoughtFrame(decision="ask", confidence=0.9, utterance="먼저 알려줄 게 있어요")
    )
    session = _build_session(fx, engine=engine, proactivity_factory=_factory)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    decision = await session.reflect()
    assert decision is not None and decision.speak is True
    proactive = [
        e
        for e in events
        if isinstance(e, ProactiveMessageEvent) and e.kind == "proactive"
    ]
    assert len(proactive) == 1
    assert proactive[0].text == "먼저 알려줄 게 있어요"


@pytest.mark.asyncio
async def test_reflect_noop_without_engine(fx):
    await fx["repo"].create(session_id="test-session")
    session = _build_session(fx, engine=None, proactivity_factory=_factory)
    assert await session.reflect() is None


@pytest.mark.asyncio
async def test_reflect_silent_does_not_push(fx):
    await fx["repo"].create(session_id="test-session")
    engine = StubEngine(ThoughtFrame(decision="silent", confidence=0.9))
    session = _build_session(fx, engine=engine, proactivity_factory=_factory)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    decision = await session.reflect()
    assert decision is not None and decision.speak is False
    assert not [e for e in events if isinstance(e, ProactiveMessageEvent)]


# ── E2: 저위험 자율 실행 이중 게이트 ──────────────────────────────────────────


class _FakeTool:
    name = "read_file"
    description = "fake read"
    parameters: dict = {"type": "object", "properties": {}}
    execution_mode = "parallel"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, tool_call_id, params, signal=None):
        from jarvis.model_layer.types import TextContent, ToolResultMessage

        self.calls.append(params)
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(text="ok")],
            is_error=False,
        )


@pytest.mark.asyncio
async def test_reflect_executes_only_safelisted_tool(fx):
    from jarvis.agent_layer.thought.types import ProactiveAction
    from jarvis.agent_layer.types import ToolExecutionEndEvent

    await fx["repo"].create(session_id="test-session")
    tool = _FakeTool()
    fx["tool_registry"].register(tool)

    # 둘 다 low-risk지만, read_file만 화이트리스트 → 실행. mutate_db는 스킵.
    frame = ThoughtFrame(
        decision="act",
        confidence=0.9,
        utterance="확인 필요",
        proactive_actions=[
            ProactiveAction(kind="tool", tool_name="read_file", description="로그", risk="low"),
            ProactiveAction(kind="tool", tool_name="mutate_db", description="변경", risk="low"),
        ],
    )
    session = _build_session(fx, engine=StubEngine(frame), proactivity_factory=_factory)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    decision = await session.reflect()

    assert decision.speak is True
    assert len(tool.calls) == 1  # read_file만 실행, mutate_db 스킵
    ends = [e for e in events if isinstance(e, ToolExecutionEndEvent)]
    assert len(ends) == 1 and ends[0].tool_name == "read_file"
    # 자율 실행 요약이 proactive 메시지에 포함.
    pmsg = [e for e in events if isinstance(e, ProactiveMessageEvent)][0]
    assert "미리 해둠" in pmsg.text


@pytest.mark.asyncio
async def test_record_feedback_updates_learner(fx):
    from jarvis.core.proactive import FeedbackLearner

    await fx["repo"].create(session_id="test-session")
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    session = _build_session(fx, engine=None, feedback_learner=learner)

    await session.record_feedback(accepted=True)
    assert learner.threshold() == pytest.approx(0.55)
    await session.record_feedback(accepted=False)
    assert learner.threshold() == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_record_feedback_noop_without_learner(fx):
    await fx["repo"].create(session_id="test-session")
    session = _build_session(fx, engine=None, feedback_learner=None)
    await session.record_feedback(accepted=True)  # 예외 없이 no-op


@pytest.mark.asyncio
async def test_proactive_event_carries_message_id(fx):
    await fx["repo"].create(session_id="test-session")
    engine = StubEngine(ThoughtFrame(decision="ask", confidence=0.9, utterance="알림"))
    session = _build_session(fx, engine=engine, proactivity_factory=_factory)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())
    await session.reflect()

    pmsgs = [e for e in events if isinstance(e, ProactiveMessageEvent)]
    assert pmsgs and pmsgs[0].message_id  # 피드백 참조용 id가 실려야 한다


class CountingEngine(StubEngine):
    def __init__(self, frame: ThoughtFrame | None) -> None:
        super().__init__(frame)
        self.requests: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        return self._frame


@pytest.mark.asyncio
async def test_reflect_skips_thought_while_awaiting_reply(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="구조화 잘 되고 있나요?"))
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    session = _build_session(fx, engine=engine, proactivity_factory=factory)
    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    assert (await session.reflect()).speak is True
    second = await session.reflect()
    assert second.speak is False and second.reason == "awaiting reply"
    assert len(engine.requests) == 1  # 기다리는 동안 사고 모델을 부르지 않는다
    assert len([e for e in events if isinstance(e, ProactiveMessageEvent)]) == 1


@pytest.mark.asyncio
async def test_feedback_releases_gate_and_reflection_sees_recent_proactive(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="구조화 잘 되고 있나요?"))
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    session = _build_session(fx, engine=engine, proactivity_factory=factory)

    await session.reflect()
    assert engine.requests[0].recent_proactive == []
    await session.record_feedback(accepted=False)
    assert (await session.reflect()).speak is True
    assert engine.requests[1].recent_proactive == ["구조화 잘 되고 있나요?"]


@pytest.mark.asyncio
async def test_user_message_releases_gate(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"))
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    session = _build_session(fx, engine=engine, proactivity_factory=factory)

    await session.reflect()
    assert session._proactivity.check_awaiting("test-session") is not None
    await session.prompt("다른 얘기")
    assert session._proactivity.check_awaiting("test-session") is None


@pytest.mark.asyncio
async def test_unanswered_proactive_learned_once_as_weak_dismiss(fx):
    from jarvis.core.proactive import FeedbackLearner

    await fx["repo"].create(session_id="test-session")
    now = [0.0]
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit,
        policy=DefaultProactivityPolicy(
            confidence_threshold=0.5, cooldown_sec=0, ignore_after_sec=600, clock=lambda: now[0]
        ),
    )
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"))
    session = _build_session(fx, engine=engine, proactivity_factory=factory, feedback_learner=learner)

    await session.reflect()
    now[0] = 700
    await session.reflect()
    await session.reflect()
    assert learner.stats()["ignores"] == 1
    assert learner.threshold() == pytest.approx(0.625)


@pytest.mark.asyncio
async def test_restart_keeps_gate_and_recent_proactive(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="구조화 잘 되고 있나요?"))
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    assert (await _build_session(fx, engine=engine, proactivity_factory=factory).reflect()).speak is True

    # 재시작: 같은 저장소로 새 세션을 만든다
    restarted = _build_session(fx, engine=engine, proactivity_factory=factory)
    second = await restarted.reflect()
    assert second.speak is False and second.reason == "awaiting reply"
    assert second.ignored is False  # 재시작 전에 셌을 수 있는 무시를 다시 세지 않는다
    assert len(engine.requests) == 1

    await restarted.prompt("응 잘 되고 있어")
    assert (await restarted.reflect()).speak is True
    assert engine.requests[1].recent_proactive == ["구조화 잘 되고 있나요?"]
    assert await fx["repo"].get_messages("test-session")  # 🔔 는 대화 기록에 섞이지 않는다
    assert all(m.role != "assistant" or "구조화" not in m.text() for m in await fx["repo"].get_messages("test-session"))


@pytest.mark.asyncio
async def test_restart_after_user_reply_does_not_close_gate(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"))
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    session = _build_session(fx, engine=engine, proactivity_factory=factory)
    await session.reflect()
    await session.prompt("답했어")

    restarted = _build_session(fx, engine=engine, proactivity_factory=factory)
    assert (await restarted.reflect()).speak is True


@pytest.mark.asyncio
async def test_restart_keeps_feedback_release_and_cooldown(fx):
    from jarvis.agent_layer.session.protocol import PROACTIVE_ACK_ENTRY

    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"))
    no_cooldown = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    session = _build_session(fx, engine=engine, proactivity_factory=no_cooldown)
    await session.reflect()
    await session.record_feedback(accepted=True)
    await session.record_feedback(accepted=True)
    assert len(await fx["repo"].get_proactive("test-session", PROACTIVE_ACK_ENTRY)) == 1  # 같은 🔔 의 피드백은 하나

    # 피드백으로 답한 🔔 는 재시작해도 대기를 다시 걸지 않는다
    assert (await _build_session(fx, engine=engine, proactivity_factory=no_cooldown).reflect()).speak is True

    # 쿨다운은 마지막 🔔 시각부터 이어 센다
    with_cooldown = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=300)
    )
    restarted = _build_session(fx, engine=engine, proactivity_factory=with_cooldown)
    await restarted.record_feedback(accepted=True)
    assert (await restarted.reflect()).reason == "cooldown"


async def _noop():
    return None
