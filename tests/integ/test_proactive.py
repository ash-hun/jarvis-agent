"""proactive 기능: 세션의 Dual-Channel 응답, 성찰 게이팅(응답 대기, 되풀이, 근거), 피드백 학습, 재시작 복원."""

import time
import pytest
import asyncio
from collections.abc import Callable

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolResultMessage, UserMessage
from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy, FeedbackLearner
from jarvis.agent_layer.thought.thought_types import ProactiveAction, ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.agent_types import ProactiveMessageEvent, ToolExecutionEndEvent
from jarvis.agent_layer.session.session_protocol import PROACTIVE_ACK_ENTRY
from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, OpenLoop
from jarvis.core.session import DUE_SOON_SEC, AgentSession, _loop_line
from tests.fixtures.grounded_loops import GroundedLoopStore

SID = "test-session"
# 성찰마다 다른 말을 건네는 사고 모델. 같은 말은 세션이 반복으로 막는다
FRESH_LINES = ("회의 자료는 다 모으셨어요?", "오늘 운동 일정 잡을까요?", "보고서 초안 봐 드릴까요?")
ANSWER = "애쉬, 가장 추천하는 공고는 시흥거모 S-1블록이에요. 월 부담 최대 139만원이고 마감은 11월 17일이에요."


class StubEngine:
    def __init__(self, frame: ThoughtFrame | None) -> None:
        self._frame = frame

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        return self._frame


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


class FakeClassifier:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, str, str]] = []

    async def classify(self, kind, text, context="", has_always=False):  # type: ignore[no-untyped-def]
        self.calls.append((kind, text, context))
        return self.verdict


class FixedLoops(InMemoryOpenLoopStore):
    def __init__(self, loops: list[OpenLoop]) -> None:
        super().__init__()
        self._loops = loops

    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]:
        return list(self._loops)


class _FakeTool:
    name = "read_file"
    description = "fake read"
    parameters: dict = {"type": "object", "properties": {}}
    execution_mode = "parallel"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, tool_call_id, params, signal=None):
        self.calls.append(params)
        return ToolResultMessage(
            tool_call_id=tool_call_id, tool_name=self.name, content=[TextContent(text="ok")], is_error=False
        )


def _core(**policy_kw) -> Callable:
    def factory(emit):
        return DefaultProactivityCore(
            emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, **policy_kw)
        )

    return factory


GATED = _core()
NO_COOLDOWN = _core(cooldown_sec=0)
ASK = ThoughtFrame(decision="ask", confidence=0.95, utterance="구조화 잘 되고 있나요?")


@pytest.fixture
def fx(faux_model, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo):
    return {
        "model": faux_model,
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }


async def _open(fx, spoke: bool = True) -> None:
    await fx["repo"].create(session_id=SID)
    if spoke:
        # 말한 적 없는 세션은 성찰하지 않는다. 사용자가 예전에 한 말 하나를 기록에 둔다
        await fx["repo"].append(SID, UserMessage(content="안녕", timestamp=0))


def _build(fx, engine=None, factory=None, learner=None, loops=None, classifier=None) -> AgentSession:
    return AgentSession(
        model=fx["model"],
        session_id=SID,
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
        thought_engine=engine,
        proactivity_factory=factory,
        feedback_learner=learner,
        openloop_store=loops if loops is not None else GroundedLoopStore(),
        reply_classifier=classifier,
    )


def _record(session: AgentSession) -> list:
    events: list = []

    async def sink(e):
        events.append(e)

    session.subscribe(sink)
    return events


def _proactive(events: list, kind: str | None = None) -> list[ProactiveMessageEvent]:
    return [e for e in events if isinstance(e, ProactiveMessageEvent) and (kind is None or e.kind == kind)]


async def _until(cond: Callable[[], bool]) -> None:
    for _ in range(200):
        if cond():
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("frame", "factory"),
    [
        (ThoughtFrame(needs_background=False, interpretation="x"), GATED),
        (ThoughtFrame(needs_background=True, filler="무시됨"), None),
    ],
)
async def test_prompt_answers_inline_without_proactive_event(fx, frame, factory):
    await _open(fx)
    session = _build(fx, engine=StubEngine(frame), factory=factory)
    events = _record(session)

    result = await session.prompt("간단한 질문")

    assert result is not None
    assert _proactive(events) == []


@pytest.mark.asyncio
async def test_prompt_deferred_sends_filler_then_answer_once_more(fx):
    await _open(fx)
    engine = StubEngine(ThoughtFrame(needs_background=True, filler="잠깐만요, 확인하고 알려드릴게요"))
    session = _build(fx, engine=engine, factory=GATED)
    events = _record(session)

    result = await session.prompt("오래 걸리는 작업")

    assert result is None
    assert [e.text for e in _proactive(events, "filler")] == ["잠깐만요, 확인하고 알려드릴게요"]
    await _until(lambda: bool(_proactive(events, "answer")))
    # 끝난 답은 화면 스트림과 별개로 answer 로 한 번 더 나간다(자리를 뜬 사람에게 닿는 외부 채널용)
    history = await fx["repo"].get_messages(SID)
    assert [a.text for a in _proactive(events, "answer")] == [history[-1].text().strip()]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("frame", "speak", "pushed"),
    [
        (ThoughtFrame(decision="ask", confidence=0.9, utterance="알려줄 게 있어요"), True, ["알려줄 게 있어요"]),
        (ThoughtFrame(decision="silent", confidence=0.9), False, []),
    ],
)
async def test_reflect_pushes_proactive_with_id_only_when_gated(fx, frame, speak, pushed):
    await _open(fx)
    session = _build(fx, engine=StubEngine(frame), factory=GATED)
    events = _record(session)

    decision = await session.reflect()

    assert decision is not None and decision.speak is speak
    assert [e.text for e in _proactive(events, "proactive")] == pushed
    assert all(e.message_id for e in _proactive(events))


@pytest.mark.asyncio
async def test_reflect_without_engine_is_noop(fx):
    await _open(fx)

    assert await _build(fx, factory=GATED).reflect() is None


@pytest.mark.asyncio
async def test_reflect_executes_only_safelisted_tool(fx):
    await _open(fx)
    tool = _FakeTool()
    fx["tool_registry"].register(tool)
    frame = ThoughtFrame(
        decision="act",
        confidence=0.9,
        utterance="확인 필요",
        proactive_actions=[
            ProactiveAction(kind="tool", tool_name="read_file", description="로그", risk="low"),
            ProactiveAction(kind="tool", tool_name="mutate_db", description="변경", risk="low"),
        ],
    )
    session = _build(fx, engine=StubEngine(frame), factory=GATED)
    events = _record(session)

    decision = await session.reflect()

    assert decision.speak is True
    assert len(tool.calls) == 1
    assert [e.tool_name for e in events if isinstance(e, ToolExecutionEndEvent)] == ["read_file"]
    assert "미리 해둠" in _proactive(events)[0].text


@pytest.mark.asyncio
async def test_record_feedback_moves_learner_threshold(fx):
    await _open(fx)
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    session = _build(fx, learner=learner)

    await session.record_feedback(accepted=True)
    after_accept = learner.threshold()
    await session.record_feedback(accepted=False)

    assert after_accept == pytest.approx(0.55)
    assert learner.threshold() == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_record_feedback_without_learner_is_noop(fx):
    await _open(fx)

    await _build(fx).record_feedback(accepted=True)


@pytest.mark.asyncio
async def test_reflect_waits_for_user_message_without_calling_thought(fx):
    await _open(fx)
    engine = CountingEngine(ASK, fresh=True)
    session = _build(fx, engine=engine, factory=NO_COOLDOWN)
    events = _record(session)
    first = await session.reflect()

    second = await session.reflect()
    thoughts_while_awaiting = len(engine.requests)
    await session.prompt("다른 얘기")
    third = await session.reflect()

    assert first.speak is True
    assert second.speak is False and second.reason == "awaiting reply"
    assert thoughts_while_awaiting == 1
    assert third.speak is True
    assert len(_proactive(events, "proactive")) == 2


@pytest.mark.asyncio
async def test_feedback_releases_gate_and_reflection_sees_recent_proactive(fx):
    await _open(fx)
    engine = CountingEngine(ASK, fresh=True)
    session = _build(fx, engine=engine, factory=NO_COOLDOWN)
    await session.reflect()

    await session.record_feedback(accepted=False)

    assert engine.requests[0].recent_proactive == []
    assert (await session.reflect()).speak is True
    assert engine.requests[1].recent_proactive == ["구조화 잘 되고 있나요?"]


@pytest.mark.asyncio
async def test_unanswered_proactive_learned_once_as_weak_dismiss(fx):
    await _open(fx)
    now = [0.0]
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    factory = _core(cooldown_sec=0, ignore_after_sec=600, clock=lambda: now[0])
    session = _build(fx, engine=CountingEngine(ASK), factory=factory, learner=learner)
    await session.reflect()

    now[0] = 700
    await session.reflect()
    await session.reflect()

    assert learner.stats()["ignores"] == 1
    assert learner.threshold() == pytest.approx(0.625)


@pytest.mark.asyncio
async def test_restart_keeps_gate_and_recent_proactive(fx):
    await _open(fx)
    engine = CountingEngine(ASK, fresh=True)
    assert (await _build(fx, engine=engine, factory=NO_COOLDOWN).reflect()).speak is True

    restarted = _build(fx, engine=engine, factory=NO_COOLDOWN)
    second = await restarted.reflect()

    assert second.speak is False and second.reason == "awaiting reply"
    assert second.ignored is False  # 재시작 전에 셌을 수 있는 무시를 다시 세지 않는다
    assert len(engine.requests) == 1
    await restarted.prompt("응 잘 되고 있어")
    assert (await restarted.reflect()).speak is True
    assert engine.requests[1].recent_proactive == ["구조화 잘 되고 있나요?"]
    # 먼저 건넨 말은 대화의 한 턴으로 한 번만 남고, 그 뒤에 사용자의 답이 온다
    history = await fx["repo"].get_messages(SID)
    said = [i for i, m in enumerate(history) if m.role == "assistant" and "구조화" in m.text()]
    reply = max(i for i, m in enumerate(history) if m.role == "user")
    assert len(said) == 1 and said[0] < reply


@pytest.mark.asyncio
async def test_restart_after_user_reply_keeps_gate_open(fx):
    await _open(fx)
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"), fresh=True)
    session = _build(fx, engine=engine, factory=NO_COOLDOWN)
    await session.reflect()
    await session.prompt("답했어")

    restarted = _build(fx, engine=engine, factory=NO_COOLDOWN)

    assert (await restarted.reflect()).speak is True


@pytest.mark.asyncio
async def test_restart_keeps_feedback_release_and_cooldown(fx):
    await _open(fx)
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="x"), fresh=True)
    session = _build(fx, engine=engine, factory=NO_COOLDOWN)
    await session.reflect()
    await session.record_feedback(accepted=True)
    await session.record_feedback(accepted=True)

    acks = await fx["repo"].get_proactive(SID, PROACTIVE_ACK_ENTRY)
    released = await _build(fx, engine=engine, factory=NO_COOLDOWN).reflect()
    restarted = _build(fx, engine=engine, factory=_core(cooldown_sec=300))
    await restarted.record_feedback(accepted=True)

    assert len(acks) == 1  # 같은 🔔 의 피드백은 하나
    assert released.speak is True
    # 쿨다운은 마지막 🔔 시각부터 이어 센다
    assert (await restarted.reflect()).reason == "cooldown"


@pytest.mark.asyncio
async def test_reflect_does_not_repeat_same_proactive_line(fx):
    await _open(fx)
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="안녕하세요! 무엇을 도와드릴까요?"))
    session = _build(fx, engine=engine, factory=NO_COOLDOWN)
    assert (await session.reflect()).speak is True
    await session.record_feedback(accepted=True)

    again = await session.reflect()

    assert again.speak is False and again.reason == "repeat"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer_ts", "utterance", "speak"),
    [
        (None, "애쉬, 시흥거모 S-1블록은 월 부담이 적어 추천드려요. 마감은 11월 17일이에요.", False),
        (None, "애쉬, 시흥거모 공고 마감이 이틀 남았어요. 오늘 서류 챙기시면 돼요.", True),
        # 오래전 답과 겹치는 🔔(그 공고의 마감 알림)는 되풀이로 보지 않는다
        (0, ANSWER, True),
    ],
)
async def test_reflect_blocks_only_restating_the_recent_answer(fx, answer_ts, utterance, speak):
    await _open(fx)
    answer = AssistantMessage(content=[TextContent(text=ANSWER)])
    if answer_ts is not None:
        answer = answer.model_copy(update={"timestamp": answer_ts})
    await fx["repo"].append(SID, answer)
    session = _build(fx, engine=StubEngine(ThoughtFrame(decision="act", confidence=0.9, utterance=utterance)),
                     factory=NO_COOLDOWN)

    decision = await session.reflect()

    assert decision.speak is speak
    if not speak:
        assert decision.reason == "repeat"


@pytest.mark.asyncio
async def test_reflect_without_conversation_skips_thought(fx):
    await _open(fx, spoke=False)
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="안녕하세요!"))

    decision = await _build(fx, engine=engine, factory=NO_COOLDOWN).reflect()

    assert decision.speak is False and decision.reason == "no conversation yet"
    assert engine.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("due_in_ms", [None, DUE_SOON_SEC * 1000, -60_000, 3 * 86_400_000, "empty"])
async def test_reflect_thinks_only_with_loop_due_soon(fx, due_in_ms):
    await _open(fx)
    now_ms = int(time.time() * 1000)
    loops = [] if due_in_ms == "empty" else [
        OpenLoop(description="x", origin_session="s", due_ms=None if due_in_ms is None else now_ms + due_in_ms)
    ]
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="안녕하세요!"))
    session = _build(fx, engine=engine, factory=NO_COOLDOWN, loops=FixedLoops(loops))

    decision = await session.reflect()

    grounded = due_in_ms not in ("empty", 3 * 86_400_000)
    assert len(engine.requests) == (1 if grounded else 0)
    assert (decision.reason == "nothing to tell") is not grounded


@pytest.mark.asyncio
async def test_reflect_skips_unchanged_input_until_new_message(fx):
    await _open(fx)
    engine = CountingEngine(ThoughtFrame(decision="silent", confidence=0.1))
    session = _build(fx, engine=engine, factory=NO_COOLDOWN)
    await session.reflect()

    again = await session.reflect()
    await session.prompt("내일 회의 몇 시였지?")
    await session.reflect()

    assert again.reason == "unchanged"
    assert [r.mode for r in engine.requests].count("reflection") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "accepts", "dismisses", "ignores"),
    [("accept", 1, 0, 0), ("dismiss", 0, 1, 0), ("other", 0, 0, 1)],
)
async def test_prompt_after_proactive_learns_reaction_without_asking(fx, verdict, accepts, dismisses, ignores):
    await _open(fx)
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    classifier = FakeClassifier(verdict)
    engine = CountingEngine(ThoughtFrame(decision="ask", confidence=0.95, utterance="회의 자료 지금 보내 드릴까요?"))
    session = _build(fx, engine=engine, factory=NO_COOLDOWN, learner=learner, classifier=classifier)
    assert (await session.reflect()).speak is True

    await session.prompt("응 보내줘")
    await _until(lambda: sum(learner.stats()[k] for k in ("accepts", "dismisses", "ignores")) >= 1)

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
def test_loop_line_states_remaining_time(ms, said):
    """사고 모델은 기한 시각과 지금을 빼다 틀렸다. 남은 시간은 코드가 말로 붙인다."""
    loop = OpenLoop(description="메일 보내기", origin_session="s", due_ms=1_000_000_000_000 + ms)

    assert _loop_line(loop, 1_000_000_000_000).endswith(f", {said})")


@pytest.mark.asyncio
async def test_say_speaks_as_agent_and_reads_next_message_as_reaction(fx):
    await _open(fx)
    classifier = FakeClassifier("accept")
    session = _build(fx, engine=CountingEngine(ThoughtFrame(decision="silent")), factory=NO_COOLDOWN,
                     classifier=classifier)
    events = _record(session)
    text = "애쉬, 새로 올라온 공고가 1건 있어요."

    spoke = await session.say(text)

    assert spoke is True
    assert [e.text for e in _proactive(events, "proactive")] == [text]
    history = await fx["repo"].get_messages(SID)
    assert history[-1].role == "assistant" and history[-1].text() == text
    assert (await session.reflect()).reason == "awaiting reply"
    await session.prompt("보여줘")
    await _until(lambda: bool(classifier.calls))
    assert classifier.calls == [("feedback", "보여줘", text)]


@pytest.mark.asyncio
async def test_say_refused_during_focus(fx):
    await _open(fx)
    session = _build(fx, factory=NO_COOLDOWN)
    session.set_turn_hook(object())  # type: ignore[arg-type]

    assert await session.say("애쉬, 새 공고예요.") is False
