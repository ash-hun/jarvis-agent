"""Proactive 배선 — session.prompt의 Dual-Channel(스텝 4) 통합."""

import pytest
import asyncio

from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy
from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from tests.fixtures.grounded_loops import GroundedLoopStore
from jarvis.agent_layer.types import ProactiveMessageEvent


class StubEngine:
    def __init__(self, frame: ThoughtFrame | None) -> None:
        self._frame = frame

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        return self._frame


def _build_session(fx, engine=None, proactivity_factory=None, feedback_learner=None):
    from jarvis.core.session import AgentSession

    session = AgentSession(
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
        openloop_store=GroundedLoopStore(),
    )
    # 성찰 연결 테스트라 사용자가 이미 말한 세션으로 둔다(말한 적 없는 세션은 성찰하지 않는다)
    session._user_spoke = True
    return session


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

    # 백그라운드 메인 루프가 답을 남길 때까지 기다린다. 고정 시간만 쉬면 느린 CI 에서 답이 아직 없다
    for _ in range(200):
        if any(isinstance(e, ProactiveMessageEvent) and e.kind == "answer" for e in events):
            break
        await asyncio.sleep(0.01)
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


# 성찰마다 다른 말을 건네는 사고 모델. 같은 말은 세션이 반복으로 막는다
FRESH_LINES = ("회의 자료는 다 모으셨어요?", "오늘 운동 일정 잡을까요?", "보고서 초안 봐 드릴까요?")


class CountingEngine(StubEngine):
    def __init__(self, frame: ThoughtFrame | None, fresh: bool = False) -> None:
        super().__init__(frame)
        self.requests: list[ThoughtRequest] = []
        self._fresh = fresh

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        n = len(self.requests) - 1
        if not self._fresh or self._frame is None or n == 0:
            return self._frame
        return self._frame.model_copy(update={"utterance": FRESH_LINES[(n - 1) % len(FRESH_LINES)]})


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
    frame = ThoughtFrame(decision="ask", confidence=0.95, utterance="구조화 잘 되고 있나요?")
    engine = CountingEngine(frame, fresh=True)
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
    frame = ThoughtFrame(decision="ask", confidence=0.95, utterance="구조화 잘 되고 있나요?")
    engine = CountingEngine(frame, fresh=True)
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
    # 먼저 건넨 말은 대화의 한 턴으로 한 번만 남고, 그 뒤에 사용자의 답이 온다
    history = await fx["repo"].get_messages("test-session")
    said = [i for i, m in enumerate(history) if m.role == "assistant" and "구조화" in m.text()]
    reply = next(i for i, m in enumerate(history) if m.role == "user")
    assert len(said) == 1 and said[0] < reply


@pytest.mark.asyncio
async def test_restart_after_user_reply_does_not_close_gate(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"), fresh=True)
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
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"), fresh=True)
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



@pytest.mark.asyncio
async def test_same_proactive_line_is_not_repeated(fx):
    """사고 모델이 방금 건넨 인사를 또 고르면 보내지 않는다. 피드백 질문이 같은 인사마다 반복되던 문제."""
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="안녕하세요! 무엇을 도와드릴까요?"))
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    session = _build_session(fx, engine=engine, proactivity_factory=factory)
    assert (await session.reflect()).speak is True
    await session.record_feedback(accepted=True)
    again = await session.reflect()
    assert again.speak is False and again.reason == "repeat"


@pytest.mark.asyncio
async def test_proactive_repeating_the_last_answer_is_not_sent(fx):
    """사고가 방금 끝난 답을 알릴 거리로 다시 고르면 보내지 않는다. 다른 일을 알리는 말은 보낸다."""
    from jarvis.model_layer.types import AssistantMessage, TextContent

    await fx["repo"].create(session_id="test-session")
    answer = "애쉬, 가장 추천하는 공고는 시흥거모 S-1블록이에요. 월 부담 최대 139만원이고 마감은 11월 17일이에요."
    await fx["repo"].append("test-session", AssistantMessage(content=[TextContent(text=answer)]))
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    repeat = "애쉬, 시흥거모 S-1블록은 월 부담이 적어 추천드려요. 마감은 11월 17일이에요."
    session = _build_session(fx, engine=StubEngine(ThoughtFrame(decision="act", confidence=0.9, utterance=repeat)),
                             proactivity_factory=factory)
    decision = await session.reflect()
    assert decision.speak is False and decision.reason == "repeat"

    other = "애쉬, 시흥거모 공고 마감이 이틀 남았어요. 오늘 서류 챙기시면 돼요."
    session = _build_session(fx, engine=StubEngine(ThoughtFrame(decision="act", confidence=0.9, utterance=other)),
                             proactivity_factory=factory)
    assert (await session.reflect()).speak is True


@pytest.mark.asyncio
async def test_old_answer_does_not_block_a_later_reminder(fx):
    """오래전 답과 겹치는 🔔(그 공고의 마감 알림)는 되풀이로 보지 않는다."""
    from jarvis.model_layer.types import AssistantMessage, TextContent

    await fx["repo"].create(session_id="test-session")
    answer = "애쉬, 가장 추천하는 공고는 시흥거모 S-1블록이에요. 마감은 11월 17일이에요."
    old = AssistantMessage(content=[TextContent(text=answer)], timestamp=0)
    await fx["repo"].append("test-session", old)
    factory = lambda emit: DefaultProactivityCore(  # noqa: E731
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )
    session = _build_session(fx, engine=StubEngine(ThoughtFrame(decision="act", confidence=0.9, utterance=answer)),
                             proactivity_factory=factory)
    assert (await session.reflect()).speak is True


@pytest.mark.asyncio
async def test_session_without_conversation_does_not_reflect(fx):
    """앱이나 화면이 세션을 열기만 했으면 사고 모델을 부르지 않는다."""
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="안녕하세요!"))
    session = _build_session(fx, engine=engine, proactivity_factory=lambda emit: DefaultProactivityCore(
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    ))
    session._user_spoke = False
    decision = await session.reflect()
    assert decision.speak is False and decision.reason == "no conversation yet" and engine.requests == []


class FakeClassifier:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, str, str]] = []

    async def classify(self, kind, text, context="", has_always=False):  # type: ignore[no-untyped-def]
        self.calls.append((kind, text, context))
        return self.verdict


def _no_cooldown(emit):
    return DefaultProactivityCore(
        emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
    )


@pytest.mark.asyncio
async def test_nothing_to_tell_does_not_call_the_thought_model(fx):
    """챙길 약속도 새 이벤트도 없으면 사고 모델을 부르지 않는다. 이때 사고는 인사나 방금 한 답을 지어 건넸다."""
    from jarvis.agent_layer.openloop import InMemoryOpenLoopStore
    from jarvis.core.session import AgentSession

    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="안녕하세요!"))
    session = AgentSession(
        model=fx["model"], session_id="test-session", security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"], memory=fx["session_memory"], tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"], session_repo=fx["repo"], thought_engine=engine,
        proactivity_factory=_no_cooldown, openloop_store=InMemoryOpenLoopStore(),
    )
    session._user_spoke = True
    decision = await session.reflect()
    assert decision.speak is False and decision.reason == "nothing to tell"
    assert engine.requests == []


@pytest.mark.asyncio
async def test_unchanged_input_is_not_reflected_twice(fx):
    """대화, 약속, 이벤트가 그대로면 다시 생각하지 않는다. 새 말이 오면 다시 본다."""
    await fx["repo"].create(session_id="test-session")
    engine = CountingEngine(ThoughtFrame(decision="silent", confidence=0.1))
    session = _build_session(fx, engine=engine, proactivity_factory=_no_cooldown)
    await session.reflect()
    again = await session.reflect()
    assert again.reason == "unchanged" and len(engine.requests) == 1
    await session.prompt("내일 회의 몇 시였지?")
    await session.reflect()
    assert [r.mode for r in engine.requests].count("reflection") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "accepts", "dismisses", "ignores"),
    [("accept", 1, 0, 0), ("dismiss", 0, 1, 0), ("other", 0, 0, 1)],
)
async def test_next_message_after_proactive_is_learned_without_asking(fx, verdict, accepts, dismisses, ignores):
    """먼저 건넨 말 뒤 첫 말을 그 말에 대한 반응으로 읽는다. 받아들임, 거절, 딴 얘기(약한 무시)."""
    from jarvis.core.proactive.feedback import FeedbackLearner

    await fx["repo"].create(session_id="test-session")
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    classifier = FakeClassifier(verdict)
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="회의 자료 지금 보내 드릴까요?"))
    session = _build_session(fx, engine=engine, proactivity_factory=_no_cooldown, feedback_learner=learner)
    session._reply_classifier = classifier
    assert (await session.reflect()).speak is True

    await session.prompt("응 보내줘")
    await asyncio.gather(*session._feedback_tasks)
    assert classifier.calls == [("feedback", "응 보내줘", "회의 자료 지금 보내 드릴까요?")]
    stats = learner.stats()
    assert (stats["accepts"], stats["dismisses"], stats["ignores"]) == (accepts, dismisses, ignores)

    # 다음 말은 먼저 건넨 말에 대한 반응이 아니다
    await session.prompt("그리고 내일 날씨는?")
    assert len(classifier.calls) == 1


@pytest.mark.parametrize(
    ("ms", "said"),
    [(240_000, "4분 남음"), (1, "1분 남음"), (0, "기한 지남"), (90 * 60_000, "1시간 30분 남음"),
     (120 * 60_000, "2시간 남음"), (3 * 86_400_000, "3일 남음")],
)
def test_remaining_time_is_computed_not_left_to_the_model(ms, said):
    """사고 모델은 기한 시각과 지금을 빼다 틀렸다. 남은 시간은 코드가 말로 붙인다."""
    from jarvis.agent_layer.openloop import OpenLoop
    from jarvis.core.session import _loop_line

    loop = OpenLoop(description="메일 보내기", origin_session="s", due_ms=1_000_000_000_000 + ms)
    assert _loop_line(loop, 1_000_000_000_000).endswith(f", {said})")


def test_only_loops_due_soon_or_without_due_are_grounds_to_speak():
    """며칠 남은 약속(추천 공고의 마감 사흘 전)은 그 시각이 다가올 때까지 먼저 말할 근거가 아니다."""
    from jarvis.core.session import DUE_SOON_SEC, _due_soon
    from jarvis.agent_layer.openloop import OpenLoop

    now = 1_000_000_000_000
    def loop(due):  # noqa: E306
        return OpenLoop(description="x", origin_session="s", due_ms=due)
    assert _due_soon(loop(None), now)
    assert _due_soon(loop(now + DUE_SOON_SEC * 1000), now) and _due_soon(loop(now - 60_000), now)
    assert not _due_soon(loop(now + 3 * 86_400_000), now)
