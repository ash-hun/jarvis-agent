"""외부 트리거 배선 — 사고 주입 / 세션 drain-once 라우팅 / 게이팅 / 트리거 합성."""

import pytest

from jarvis.core.proactive import (
    ActivityClock,
    AnyTrigger,
    DefaultProactivityCore,
    DefaultProactivityPolicy,
    ExternalTrigger,
    IntervalTrigger,
)
from jarvis.agent_layer.thought.prompt import (
    DEFAULT_REFLECTION_TEMPLATE,
    ThoughtPromptTemplate,
)
from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.core.external import ExternalEvent, ExternalEventInbox
from jarvis.agent_layer.thought.engine import InnerThoughtEngine
from tests.fixtures.grounded_loops import GroundedLoopStore
from jarvis.agent_layer.types import ProactiveMessageEvent


class StubEngine:
    """think()에 들어온 요청을 기록하는 스텁 — 주입 경로 검증용."""

    def __init__(self, frame: ThoughtFrame | None) -> None:
        self._frame = frame
        self.requests: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        return self._frame


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


def _build_session(fx, session_id, *, engine=None, inbox=None, detail=False, factory=None):
    from jarvis.core.session import AgentSession

    session = AgentSession(
        model=fx["model"],
        session_id=session_id,
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
        thought_engine=engine,
        proactivity_factory=factory,
        external_inbox=inbox,
        external_detail_in_prompt=detail,
        openloop_store=GroundedLoopStore(),
    )
    # 성찰 연결 테스트라 사용자가 이미 말한 세션으로 둔다(말한 적 없는 세션은 성찰하지 않는다)
    session._user_spoke = True
    return session


def _speaking_factory(threshold: float = 0.5):
    def factory(emit):
        return DefaultProactivityCore(
            emit_proactive=emit,
            policy=DefaultProactivityPolicy(confidence_threshold=threshold, cooldown_sec=0),
        )

    return factory


def _event(key: str, title: str = "회의 30분 후", detail: str = "본문 원문") -> ExternalEvent:
    return ExternalEvent(source="cal", key=key, title=title, detail=detail)


# ── 사고 주입 ────────────────────────────────────────────────────────────────


def test_reflection_template_renders_external_events():
    template = ThoughtPromptTemplate(DEFAULT_REFLECTION_TEMPLATE)
    engine = InnerThoughtEngine(model=None, reflection_template=template)  # type: ignore[arg-type]
    prompt = engine._render(
        ThoughtRequest(user_input="x", mode="reflection", external_events=["[cal] 회의 30분 후"]),
        [],
    )
    assert "[외부 이벤트]" in prompt
    assert "- [cal] 회의 30분 후" in prompt


def test_edited_template_without_placeholder_gets_appended_block():
    edited = ThoughtPromptTemplate("나만의 성찰 템플릿\n[최근 대화] {{history}}")
    engine = InnerThoughtEngine(model=None, reflection_template=edited)  # type: ignore[arg-type]
    prompt = engine._render(
        ThoughtRequest(user_input="x", mode="reflection", external_events=["[cal] 회의"]),
        [],
    )
    assert prompt.endswith("[외부 이벤트]\n- [cal] 회의")


def test_no_events_leaves_prompt_unchanged():
    edited = ThoughtPromptTemplate("나만의 성찰 템플릿")
    engine = InnerThoughtEngine(model=None, reflection_template=edited)  # type: ignore[arg-type]
    prompt = engine._render(ThoughtRequest(user_input="x", mode="reflection"), [])
    assert prompt == "나만의 성찰 템플릿"


# ── 세션 drain 라우팅 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reflect_feeds_external_events_to_thought(fx):
    await fx["repo"].create(session_id="s1")
    inbox = ExternalEventInbox()
    inbox.put([_event("cal:1")])
    engine = StubEngine(ThoughtFrame(decision="silent", confidence=0.1))
    session = _build_session(fx, "s1", engine=engine, inbox=inbox, factory=_speaking_factory())

    await session.reflect()

    assert len(engine.requests) == 1
    lines = engine.requests[0].external_events
    assert lines and lines[0].startswith("[cal] 회의 30분 후")
    assert engine.requests[0].mode == "reflection"


@pytest.mark.asyncio
async def test_detail_is_withheld_from_prompt_by_default(fx):
    await fx["repo"].create(session_id="s1")
    inbox = ExternalEventInbox()
    inbox.put([_event("cal:1")])
    engine = StubEngine(ThoughtFrame(decision="silent"))
    session = _build_session(fx, "s1", engine=engine, inbox=inbox, factory=_speaking_factory())

    await session.reflect()
    assert "본문 원문" not in engine.requests[0].external_events[0]


@pytest.mark.asyncio
async def test_detail_is_included_when_configured(fx):
    await fx["repo"].create(session_id="s1")
    inbox = ExternalEventInbox()
    inbox.put([_event("cal:1")])
    engine = StubEngine(ThoughtFrame(decision="silent"))
    session = _build_session(
        fx, "s1", engine=engine, inbox=inbox, detail=True, factory=_speaking_factory()
    )

    await session.reflect()
    assert "본문 원문" in engine.requests[0].external_events[0]


@pytest.mark.asyncio
async def test_shared_inbox_is_drained_once_across_sessions(fx):
    await fx["repo"].create(session_id="s1")
    await fx["repo"].create(session_id="s2")
    inbox = ExternalEventInbox()
    inbox.put([_event("cal:1")])

    first_engine = StubEngine(ThoughtFrame(decision="silent"))
    second_engine = StubEngine(ThoughtFrame(decision="silent"))
    first = _build_session(fx, "s1", engine=first_engine, inbox=inbox, factory=_speaking_factory())
    second = _build_session(
        fx, "s2", engine=second_engine, inbox=inbox, factory=_speaking_factory()
    )

    await first.reflect()
    await second.reflect()

    assert first_engine.requests[0].external_events
    assert second_engine.requests[0].external_events == []


@pytest.mark.asyncio
async def test_external_event_is_consumed_by_first_reflecting_session(fx):
    await fx["repo"].create(session_id="s1")
    await fx["repo"].create(session_id="s2")
    inbox = ExternalEventInbox()
    inbox.put([_event("cal:1")])

    spoken: list[ProactiveMessageEvent] = []

    async def sink(event):
        if isinstance(event, ProactiveMessageEvent):
            spoken.append(event)

    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="회의 임박")
    first = _build_session(fx, "s1", engine=StubEngine(frame), inbox=inbox,
                           factory=_speaking_factory())
    second = _build_session(fx, "s2", engine=StubEngine(frame), inbox=inbox,
                            factory=_speaking_factory())
    first.subscribe(sink)
    second.subscribe(sink)

    await first.reflect()
    assert len(spoken) == 1

    # 두 번째 세션은 빈 inbox로 성찰한다 — 같은 외부 이벤트가 두 번 실리지 않는다.
    # (세션 자체의 성찰 발화 여부는 종전대로 정책이 정한다.)
    spoken.clear()
    await second.reflect()
    assert second._external_inbox is not None
    assert len(second._external_inbox) == 0


@pytest.mark.asyncio
async def test_low_confidence_event_stays_silent(fx):
    await fx["repo"].create(session_id="s1")
    inbox = ExternalEventInbox()
    inbox.put([_event("cal:1")])
    spoken: list[ProactiveMessageEvent] = []

    async def sink(event):
        if isinstance(event, ProactiveMessageEvent):
            spoken.append(event)

    session = _build_session(
        fx,
        "s1",
        engine=StubEngine(ThoughtFrame(decision="act", confidence=0.2)),
        inbox=inbox,
        factory=_speaking_factory(threshold=0.8),
    )
    session.subscribe(sink)

    await session.reflect()
    assert spoken == []


@pytest.mark.asyncio
async def test_session_without_inbox_behaves_as_before(fx):
    await fx["repo"].create(session_id="s1")
    engine = StubEngine(ThoughtFrame(decision="silent"))
    session = _build_session(fx, "s1", engine=engine, factory=_speaking_factory())

    await session.reflect()
    assert engine.requests[0].external_events == []


# ── 트리거 합성 / 폴러 배선 ──────────────────────────────────────────────────


def test_external_trigger_is_composed_regardless_of_daemon_mode():
    from jarvis.app.infra_builder import InfraBuilder
    from jarvis.config import JarvisSettings

    settings = JarvisSettings()
    settings.proactive.daemon_trigger = "interval"
    external = ExternalTrigger()

    trigger = InfraBuilder(settings).build_reflection_trigger(ActivityClock(), external)
    assert isinstance(trigger, AnyTrigger)
    assert external in trigger._triggers

    plain = InfraBuilder(settings).build_reflection_trigger(ActivityClock(), None)
    assert isinstance(plain, IntervalTrigger)


def test_build_external_is_noop_without_sources(tmp_path):
    from jarvis.app.infra_builder import InfraBuilder
    from jarvis.config import JarvisSettings

    settings = JarvisSettings()
    settings.external.sources_dir = str(tmp_path / "missing")
    assert InfraBuilder(settings).build_external() == (None, None, None)


def test_build_external_builds_poller_from_yaml(tmp_path):
    from jarvis.config import JarvisSettings, MCPServerConfig
    from jarvis.app.infra_builder import InfraBuilder

    sources_dir = tmp_path / "external_sources"
    sources_dir.mkdir()
    (sources_dir / "cal.yaml").write_text(
        "- name: calendar-upcoming\n"
        "  server: gcal\n"
        "  tool: list_events\n"
        "  interval_sec: 60\n",
        encoding="utf-8",
    )

    settings = JarvisSettings()
    settings.external.sources_dir = str(sources_dir)
    settings.external.seen_backend = "in_memory"
    settings.mcp_servers = [MCPServerConfig(name="gcal", command=["x"])]

    inbox, poller, trigger = InfraBuilder(settings).build_external()
    assert inbox is not None and poller is not None
    assert isinstance(trigger, ExternalTrigger)
    assert [s.name for s in poller._sources] == ["calendar-upcoming"]


def test_build_external_skips_when_disabled():
    from jarvis.app.infra_builder import InfraBuilder
    from jarvis.config import JarvisSettings

    settings = JarvisSettings()
    settings.external.enabled = False
    assert InfraBuilder(settings).build_external() == (None, None, None)


@pytest.mark.asyncio
async def test_poller_to_proactive_message_end_to_end(fx):
    """소스 폴링 → dedup → inbox → 성찰 → 발화까지 실제 객체로 한 번에 잇는다."""
    from jarvis.core.external import (
        ExternalEventPoller,
        InMemorySeenStore,
        McpToolSource,
    )
    from jarvis.core.external.loader import ExternalSourceSpec
    from jarvis.config import MCPServerConfig

    await fx["repo"].create(session_id="s1")

    async def fake_call(server, tool, params):
        return '[{"id": "e1", "summary": "3시 디자인 리뷰", "start": "2026-09-02T15:00:00"}]'

    source = McpToolSource(
        ExternalSourceSpec(name="calendar", server="gcal", tool="list_events"),
        MCPServerConfig(name="gcal", command=["x"]),
        call=fake_call,
    )
    inbox = ExternalEventInbox()
    trigger = ExternalTrigger()
    poller = ExternalEventPoller([source], inbox, InMemorySeenStore(), trigger=trigger)

    assert await poller.tick() == 1

    engine = StubEngine(ThoughtFrame(decision="act", confidence=0.9, utterance="곧 회의"))
    spoken: list[ProactiveMessageEvent] = []

    async def sink(event):
        if isinstance(event, ProactiveMessageEvent):
            spoken.append(event)

    session = _build_session(fx, "s1", engine=engine, inbox=inbox, factory=_speaking_factory())
    session.subscribe(sink)

    await session.reflect()

    assert "3시 디자인 리뷰" in engine.requests[0].external_events[0]
    assert len(spoken) == 1

    # 두 번째 폴링은 같은 이벤트를 다시 올리지 않는다(dedup).
    assert await poller.tick() == 0
