"""thought 기능: ws reply_classify 판정, 세션의 사고 이벤트와 로그, 시점, router 와 다음 턴 주입, 성찰 범위."""

import pytest
import asyncio

pytest.importorskip("fastapi")

from jarvis.agent_layer.agent_types import InnerThoughtEvent, ThoughtEndEvent, ThoughtRouteEvent  # noqa: E402
from jarvis.agent_layer.thought import LTMThoughtSink, ThoughtFrame, ThoughtLog, ThoughtRequest  # noqa: E402
from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402
from jarvis.agent_layer.thought.reply import ReplyClassifier  # noqa: E402
from jarvis.memory.stores.in_memory import InMemoryItemStore  # noqa: E402
from tests.fixtures.grounded_loops import GroundedLoopStore  # noqa: E402
from jarvis.agent_layer.thought.router import RouteVerdict  # noqa: E402
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE  # noqa: E402
from jarvis.core.proactive import DefaultProactivityCore  # noqa: E402
from jarvis.memory.memory_service import MemoryService  # noqa: E402
from jarvis.model_layer.model_types import UserMessage  # noqa: E402
from tests.fixtures.faux_provider import FauxProvider  # noqa: E402
from jarvis.core.session import AgentSession  # noqa: E402
from jarvis.memory.scope import MemoryScope  # noqa: E402


def test_reply_classify_records_feedback_once(monkeypatch, tmp_path):
    calls: list[bool] = []

    async def fake_classify(self, kind, text, context="", has_always=False):
        return "accept" if kind == "feedback" else "allow"

    async def fake_record(self, accepted):
        calls.append(accepted)

    monkeypatch.setattr(ReplyClassifier, "classify", fake_classify)
    monkeypatch.setattr(AgentSession, "record_feedback", fake_record)
    want = {"type": "reply_classified", "kind": "feedback", "id": "p1", "verdict": "accept"}

    with web_client(web_assembly(monkeypatch, tmp_path, THOUGHT__ENABLED="true")) as c, c.websocket_connect(
        "/ws?session_id=wsreply"
    ) as ws:
        hello = ws.receive_json()
        feedback = []
        for _ in range(2):  # 같은 🔔 에 두 번 와도 학습은 한 번
            ws.send_json({"type": "reply_classify", "kind": "feedback", "id": "p1", "text": "응 그걸로 해줘"})
            feedback.append(ws.receive_json())
        ws.send_json({"type": "proactive_feedback", "id": "p1", "accepted": False})
        # 승인 분류는 판정만 돌려주고 승인 자체는 화면이 approval_response 로 보낸다
        ws.send_json({"type": "reply_classify", "kind": "approval", "id": "a1", "text": "그거 돌려", "context": "ls"})
        approval = ws.receive_json()

    assert hello["reply_classifier"] is True
    assert feedback == [want, want]
    assert approval["verdict"] == "allow"
    assert calls == [True]


def test_reply_classify_without_thought_falls_back(monkeypatch, tmp_path):
    with web_client(web_assembly(monkeypatch, tmp_path, THOUGHT__ENABLED="false")) as c, c.websocket_connect(
        "/ws?session_id=default"
    ) as ws:
        hello = ws.receive_json()
        ws.send_json({"type": "reply_classify", "kind": "approval", "id": "a1", "text": "그거 돌려"})
        approval = ws.receive_json()
        ws.send_json({"type": "reply_classify", "kind": "feedback", "id": "p1", "text": "응 그걸로"})
        feedback = ws.receive_json()

    assert hello["reply_classifier"] is False
    assert approval["verdict"] == "unclear"
    assert feedback["verdict"] == "other"


FRAME = ThoughtFrame(interpretation="일정 충돌을 걱정한다", decision="silent", confidence=0.4)


class RecordingProvider(FauxProvider):
    """메인 응답 호출마다 받은 시스템 프롬프트를 남긴다."""

    def __init__(self) -> None:
        super().__init__(response="네")
        self.system_prompts: list[str | None] = []

    async def stream(self, model, context, options=None):  # type: ignore[no-untyped-def]
        self.system_prompts.append(context.system_prompt)
        async for event in super().stream(model, context, options):
            yield event


class StubEngine:
    """고정 프레임을 delay 뒤에 돌려주는 사고 엔진."""

    def __init__(self, frame: ThoughtFrame | None, delay: float = 0.0) -> None:
        self._frame = frame
        self.delay = delay
        self.calls: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.calls.append(request)
        await asyncio.sleep(self.delay)
        return self._frame


class GateEngine:
    """release 될 때까지 끝나지 않는 사고. 응답이 사고를 기다리지 않는지 본다."""

    def __init__(self, frame: ThoughtFrame | None = FRAME) -> None:
        self._frame = frame
        self.release = asyncio.Event()
        self.calls: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.calls.append(request)
        await self.release.wait()
        return self._frame


class ScopeCapturingEngine:
    """사고 요청에 실린 범위를 기록한다. 회상은 이 범위로 기억을 읽는다."""

    def __init__(self) -> None:
        self.seen: list[MemoryScope] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.seen.append(
            MemoryScope(user_id=request.user_id or "", agent_id=request.agent_id or "", session_id=request.session_id)
        )
        return ThoughtFrame()


class FixedRouter:
    def __init__(self, *verdicts: RouteVerdict) -> None:
        self._verdicts = list(verdicts)
        self.inputs: list[str] = []

    async def route(self, user_input, history) -> RouteVerdict:  # type: ignore[no-untyped-def]
        self.inputs.append(user_input)
        return self._verdicts.pop(0) if len(self._verdicts) > 1 else self._verdicts[0]


@pytest.fixture
def provider(monkeypatch) -> RecordingProvider:  # type: ignore[no-untyped-def]
    from jarvis.model_layer.model_registry import get_default_registry

    recording = RecordingProvider()
    monkeypatch.setitem(get_default_registry()._providers, "faux", recording)
    return recording


@pytest.fixture
async def build(
    provider, faux_model, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
):  # type: ignore[no-untyped-def]
    async def _build(engine=None, router=None, timing="race", wait_sec=3.0, log=None, session_id="s", **kw):  # type: ignore[no-untyped-def]
        await jsonl_repo.create(session_id=session_id)
        session = AgentSession(
            model=faux_model,
            session_id=session_id,
            security_pipeline=permissive_pipeline,
            plugin_runner=plugin_runner,
            memory=session_memory,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            session_repo=jsonl_repo,
            thought_engine=engine,
            thought_log=log,
            thought_timing=timing,
            thought_wait_sec=wait_sec,
            thought_router=router,
            **kw,
        )
        events: list = []

        async def sink(event) -> None:  # type: ignore[no-untyped-def]
            events.append(event)

        session.subscribe(sink)
        return session, events

    _build.repo = jsonl_repo  # type: ignore[attr-defined]
    return _build


def _of(events: list, kind: type) -> list:
    return [e for e in events if isinstance(e, kind)]


async def test_prompt_emits_inner_thought_event(build):
    engine = StubEngine(ThoughtFrame(interpretation="불안함 감지", decision="ask", confidence=0.7))
    session, events = await build(engine)

    await session.prompt("배포 상태 알려줘")

    thoughts = _of(events, InnerThoughtEvent)
    assert [(e.decision, e.interpretation) for e in thoughts] == [("ask", "불안함 감지")]
    assert engine.calls[0].user_input == "배포 상태 알려줘"


async def test_prompt_stores_thought_log_in_session_scope(build):
    backend = MemoryService(InMemoryItemStore())
    engine = StubEngine(ThoughtFrame(interpretation="x", decision="silent", confidence=0.1))
    session, _ = await build(engine, log=ThoughtLog([LTMThoughtSink(backend)]))

    await session.prompt("안녕하세요 잘 지내시나요")

    entries = await backend.recent(session.memory_scope, limit=10)
    assert len(entries) == 1
    assert entries[0].source == THOUGHT_SOURCE
    assert entries[0].scope == session.memory_scope


async def test_prompt_without_engine_asks_no_router_and_emits_no_thought(build):
    router = FixedRouter(RouteVerdict(think=True, p_think=0.9))
    session, events = await build(None, router)

    await session.prompt("안녕")

    assert router.inputs == []
    assert _of(events, ThoughtRouteEvent) == []
    assert _of(events, InnerThoughtEvent) == []


async def test_prompt_completes_when_engine_returns_none(build):
    session, _ = await build(StubEngine(None))

    assert await session.prompt("뭔가 물어봄") is not None


async def test_race_timing_late_thought_does_not_block_turn_and_still_records(build):
    engine = StubEngine(ThoughtFrame(interpretation="늦은 해석", decision="silent", confidence=0.3), delay=0.3)
    session, events = await build(engine, wait_sec=0.05)
    started = asyncio.get_running_loop().time()

    await session.prompt("배포 상태 알려줘")

    assert _of(events, InnerThoughtEvent) == []
    assert asyncio.get_running_loop().time() - started < 0.3
    await asyncio.sleep(0.4)
    assert [e.interpretation for e in _of(events, InnerThoughtEvent)] == ["늦은 해석"]


async def test_after_timing_runs_thought_once_reply_is_done(build):
    engine = StubEngine(ThoughtFrame(interpretation="뒤늦은 해석", decision="silent", confidence=0.3))
    session, events = await build(engine, timing="after")

    await session.prompt("배포 상태 알려줘")

    assert engine.calls == [] or not _of(events, InnerThoughtEvent)
    await asyncio.sleep(0.05)
    assert [e.interpretation for e in _of(events, InnerThoughtEvent)] == ["뒤늦은 해석"]


async def test_before_timing_waits_even_when_slow(build):
    engine = StubEngine(ThoughtFrame(interpretation="느린 해석", decision="silent", confidence=0.3), delay=0.1)
    session, events = await build(engine, timing="before", wait_sec=0.01)

    await session.prompt("배포 상태 알려줘")

    assert [e.interpretation for e in _of(events, InnerThoughtEvent)] == ["느린 해석"]


async def test_direct_route_replies_without_thought(build):
    engine = GateEngine()
    session, events = await build(engine, FixedRouter(RouteVerdict(think=False, p_think=0.01)))

    assert await session.prompt("거실 불 꺼줘") is not None

    assert engine.calls == []
    assert [(e.think, e.p_think) for e in _of(events, ThoughtRouteEvent)] == [(False, 0.01)]
    assert _of(events, ThoughtEndEvent) == []


async def test_think_route_runs_beside_the_reply_and_feeds_the_next_turn_once(build, provider):
    engine = GateEngine()
    session, events = await build(engine, FixedRouter(RouteVerdict(think=True, p_think=0.8)))

    await asyncio.wait_for(session.prompt("다음 주 일정 짜줘"), timeout=1.0)

    assert [c.user_input for c in engine.calls] == ["다음 주 일정 짜줘"]
    assert _of(events, ThoughtEndEvent) == []
    assert "[내적 사고]" not in (provider.system_prompts[0] or "")

    engine.release.set()
    await session.settle()

    assert [e.ok for e in _of(events, ThoughtEndEvent)] == [True]
    assert [e.interpretation for e in _of(events, InnerThoughtEvent)] == ["일정 충돌을 걱정한다"]

    await session.prompt("응 그렇게 해")
    await session.settle()
    await session.prompt("고마워")

    assert "일정 충돌을 걱정한다" in (provider.system_prompts[1] or "")
    # 둘째 턴도 think 라 사고가 다시 돌지만 셋째 턴에 같은 프레임이 쌓이지 않고 하나만 들어간다
    assert (provider.system_prompts[2] or "").count("[내적 사고]") == 1


async def test_pending_thought_is_used_once(build, provider):
    engine = GateEngine()
    engine.release.set()
    router = FixedRouter(RouteVerdict(think=True, p_think=0.8), RouteVerdict(think=False, p_think=0.0))
    session, _ = await build(engine, router)

    await session.prompt("일정 짜줘")
    await session.settle()
    await session.prompt("응")
    await session.prompt("고마워")

    assert "[내적 사고]" in (provider.system_prompts[1] or "")
    assert "[내적 사고]" not in (provider.system_prompts[2] or "")


async def test_failed_thought_still_ends(build, provider):
    engine = GateEngine(frame=None)
    engine.release.set()
    session, events = await build(engine, FixedRouter(RouteVerdict(think=True, p_think=None)))

    await session.prompt("분석해줘")
    await session.settle()
    await session.prompt("다음")

    assert [e.ok for e in _of(events, ThoughtEndEvent)][:1] == [False]
    assert "[내적 사고]" not in (provider.system_prompts[1] or "")


async def test_router_overrides_before_timing(build):
    """router 가 있으면 request_timing 대신 router 가 정한다. before 여도 사고를 기다리지 않는다."""
    engine = GateEngine()
    session, _ = await build(engine, FixedRouter(RouteVerdict(think=True, p_think=0.9)), timing="before")

    await asyncio.wait_for(session.prompt("비교해줘"), timeout=1.0)

    engine.release.set()
    await session.settle()


async def test_reflect_thinks_in_its_own_session_scope(build):
    engine = ScopeCapturingEngine()
    kw = {"proactivity_factory": lambda emit: DefaultProactivityCore(emit_proactive=emit)}
    first, _ = await build(engine, session_id="s1", openloop_store=GroundedLoopStore(), **kw)
    second, _ = await build(engine, session_id="s2", openloop_store=GroundedLoopStore(), **kw)
    # 말한 적 없는 세션은 성찰하지 않으므로 사용자가 이미 말한 세션으로 둔다
    await build.repo.append("s1", UserMessage(content="안녕"))
    await build.repo.append("s2", UserMessage(content="안녕"))

    await first.reflect()
    await second.reflect()

    assert [s.session_id for s in engine.seen] == ["s1", "s2"]
    assert engine.seen[0] == first.memory_scope
