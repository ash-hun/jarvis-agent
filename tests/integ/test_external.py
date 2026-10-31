"""external 기능 통합: 폴러, inbox, 세션 성찰, 사고 프롬프트, 앱 조립이 외부 이벤트를 한 번만 실어 나르는지 검증한다."""

import pytest
import asyncio
from collections.abc import AsyncIterator

from jarvis.core.external import (
    ExternalEvent,
    ExternalEventInbox,
    ExternalEventPoller,
    ExternalSourceSpec,
    InMemorySeenStore,
    McpToolSource,
)
from jarvis.model_layer.model_types import (
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    Usage,
    UserMessage,
)
from jarvis.core.proactive import (
    ActivityClock,
    DefaultProactivityCore,
    DefaultProactivityPolicy,
    ExternalTrigger,
    IntervalTrigger,
)
from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE, ThoughtPromptTemplate
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.model_layer.model_registry import get_default_registry
from jarvis.agent_layer.agent_types import ProactiveMessageEvent
from jarvis.agent_layer.thought.engine import InnerThoughtEngine
from jarvis.jarvis_config import JarvisSettings, MCPServerConfig
from tests.fixtures.grounded_loops import GroundedLoopStore
from jarvis.app.infra_builder import InfraBuilder
from jarvis.core.session import AgentSession

RECORDER = "prompt_recorder"


class PromptRecorder:
    """사고 엔진이 모델에 보낸 프롬프트를 기록하는 가짜 프로바이더."""

    provider_name = RECORDER

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.prompts.append(context.messages[-1].content)  # type: ignore[union-attr]
        yield TextDeltaEvent(delta='{"decision": "silent"}')
        yield StopEvent(reason="stop", usage=Usage(input=1, output=1))


class StubEngine:
    """think()에 들어온 요청을 기록하는 스텁."""

    def __init__(self, frame: ThoughtFrame | None) -> None:
        self._frame = frame
        self.requests: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        return self._frame


@pytest.fixture
def recorder() -> PromptRecorder:
    registry = get_default_registry()
    registry.register(PromptRecorder())
    provider = registry.get(RECORDER)
    provider.prompts.clear()  # type: ignore[attr-defined]
    return provider  # type: ignore[return-value]


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


async def _build_session(fx, session_id, *, engine, inbox=None, detail=False, threshold=0.5) -> AgentSession:
    await fx["repo"].create(session_id=session_id)
    # 말한 적 없는 세션은 성찰하지 않으므로 사용자가 이미 말한 세션으로 둔다
    await fx["repo"].append(session_id, UserMessage(content="안녕"))

    def factory(emit):
        return DefaultProactivityCore(
            emit_proactive=emit,
            policy=DefaultProactivityPolicy(confidence_threshold=threshold, cooldown_sec=0),
        )

    return AgentSession(
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


def _inbox_with(key: str = "cal:1") -> ExternalEventInbox:
    inbox = ExternalEventInbox()
    inbox.put([ExternalEvent(source="cal", key=key, title="회의 30분 후", detail="본문 원문")])
    return inbox


def _collect(session: AgentSession) -> list[ProactiveMessageEvent]:
    spoken: list[ProactiveMessageEvent] = []

    async def sink(event):
        if isinstance(event, ProactiveMessageEvent):
            spoken.append(event)

    session.subscribe(sink)
    return spoken


def _reflection(external_events: list[str] | None = None) -> ThoughtRequest:
    return ThoughtRequest(user_input="x", mode="reflection", external_events=external_events or [])


@pytest.mark.asyncio
async def test_reflection_prompt_renders_external_events(recorder: PromptRecorder) -> None:
    template = ThoughtPromptTemplate(DEFAULT_REFLECTION_TEMPLATE)
    engine = InnerThoughtEngine(ModelConfig(provider=RECORDER, model="m"), reflection_template=template)

    await engine.think(_reflection(["[cal] 회의 30분 후"]))

    assert "[외부 이벤트]" in recorder.prompts[0]
    assert "- [cal] 회의 30분 후" in recorder.prompts[0]


@pytest.mark.asyncio
async def test_reflection_prompt_appends_events_to_template_without_placeholder(recorder: PromptRecorder) -> None:
    edited = ThoughtPromptTemplate("나만의 성찰 템플릿\n[최근 대화] {{history}}")
    engine = InnerThoughtEngine(ModelConfig(provider=RECORDER, model="m"), reflection_template=edited)

    await engine.think(_reflection(["[cal] 회의"]))

    assert recorder.prompts[0].endswith("[외부 이벤트]\n- [cal] 회의")


@pytest.mark.asyncio
async def test_reflection_prompt_unchanged_without_events(recorder: PromptRecorder) -> None:
    edited = ThoughtPromptTemplate("나만의 성찰 템플릿")
    engine = InnerThoughtEngine(ModelConfig(provider=RECORDER, model="m"), reflection_template=edited)

    await engine.think(_reflection())

    assert recorder.prompts[0] == "나만의 성찰 템플릿"


@pytest.mark.asyncio
async def test_reflect_feeds_external_events_to_thought(fx) -> None:
    engine = StubEngine(ThoughtFrame(decision="silent", confidence=0.1))
    session = await _build_session(fx, "s1", engine=engine, inbox=_inbox_with())

    await session.reflect()

    assert len(engine.requests) == 1
    assert engine.requests[0].mode == "reflection"
    assert engine.requests[0].external_events[0].startswith("[cal] 회의 30분 후")


@pytest.mark.parametrize(("detail", "included"), [(False, False), (True, True)], ids=["default_withheld", "configured"])
@pytest.mark.asyncio
async def test_reflect_includes_event_detail_only_when_configured(fx, detail: bool, included: bool) -> None:
    engine = StubEngine(ThoughtFrame(decision="silent"))
    session = await _build_session(fx, "s1", engine=engine, inbox=_inbox_with(), detail=detail)

    await session.reflect()

    assert ("본문 원문" in engine.requests[0].external_events[0]) is included


@pytest.mark.asyncio
async def test_shared_inbox_is_consumed_by_first_reflecting_session(fx) -> None:
    inbox = _inbox_with()
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="회의 임박")
    first_engine, second_engine = StubEngine(frame), StubEngine(frame)
    first = await _build_session(fx, "s1", engine=first_engine, inbox=inbox)
    second = await _build_session(fx, "s2", engine=second_engine, inbox=inbox)
    spoken = _collect(first)

    await first.reflect()
    await second.reflect()

    assert len(spoken) == 1
    assert first_engine.requests[0].external_events
    assert second_engine.requests[0].external_events == []
    assert len(inbox) == 0


@pytest.mark.asyncio
async def test_reflect_stays_silent_on_low_confidence_event(fx) -> None:
    engine = StubEngine(ThoughtFrame(decision="act", confidence=0.2))
    session = await _build_session(fx, "s1", engine=engine, inbox=_inbox_with(), threshold=0.8)
    spoken = _collect(session)

    await session.reflect()

    assert spoken == []


@pytest.mark.asyncio
async def test_reflect_without_inbox_sends_no_events(fx) -> None:
    engine = StubEngine(ThoughtFrame(decision="silent"))
    session = await _build_session(fx, "s1", engine=engine)

    await session.reflect()

    assert engine.requests[0].external_events == []


@pytest.mark.asyncio
async def test_reflection_trigger_wakes_on_external_regardless_of_daemon_mode() -> None:
    settings = JarvisSettings()
    settings.proactive.daemon_trigger = "interval"
    external = ExternalTrigger()
    trigger = InfraBuilder(settings).build_reflection_trigger(ActivityClock(), external)

    external.fire()

    await asyncio.wait_for(trigger.wait(), timeout=1.0)
    assert isinstance(InfraBuilder(settings).build_reflection_trigger(ActivityClock(), None), IntervalTrigger)


@pytest.mark.parametrize("case", ["no_sources", "disabled"])
def test_build_external_is_noop_without_sources_or_when_disabled(tmp_path, case: str) -> None:
    settings = JarvisSettings()
    if case == "disabled":
        settings.external.enabled = False
    else:
        settings.external.sources_dir = str(tmp_path / "missing")

    assert InfraBuilder(settings).build_external() == (None, None, None)


@pytest.mark.asyncio
async def test_build_external_builds_poller_from_yaml(tmp_path, monkeypatch) -> None:
    sources_dir = tmp_path / "external_sources"
    sources_dir.mkdir()
    (sources_dir / "cal.yaml").write_text(
        "- name: calendar-upcoming\n  server: gcal\n  tool: list_events\n  interval_sec: 60\n", encoding="utf-8"
    )
    settings = JarvisSettings()
    settings.external.sources_dir = str(sources_dir)
    settings.external.seen_backend = "in_memory"
    settings.mcp_servers = [MCPServerConfig(name="gcal", command=["x"])]

    async def fake_call(server, tool, params):
        return '[{"id": "e1"}]'

    monkeypatch.setattr("jarvis.core.tools.mcp_loader.call_mcp_tool", fake_call)
    inbox, poller, trigger = InfraBuilder(settings).build_external()

    assert inbox is not None and poller is not None
    assert isinstance(trigger, ExternalTrigger)
    assert await poller.tick() == 1
    assert [e.source for e in inbox.drain()] == ["calendar-upcoming"]


@pytest.mark.asyncio
async def test_poller_to_proactive_message_end_to_end(fx) -> None:
    async def fake_call(server, tool, params):
        return '[{"id": "e1", "summary": "3시 디자인 리뷰", "start": "2026-09-02T15:00:00"}]'

    source = McpToolSource(
        ExternalSourceSpec(name="calendar", server="gcal", tool="list_events"),
        MCPServerConfig(name="gcal", command=["x"]),
        call=fake_call,
    )
    inbox = ExternalEventInbox()
    poller = ExternalEventPoller([source], inbox, InMemorySeenStore(), trigger=ExternalTrigger())
    assert await poller.tick() == 1
    engine = StubEngine(ThoughtFrame(decision="act", confidence=0.9, utterance="곧 회의"))
    session = await _build_session(fx, "s1", engine=engine, inbox=inbox)
    spoken = _collect(session)

    await session.reflect()

    assert "3시 디자인 리뷰" in engine.requests[0].external_events[0]
    assert len(spoken) == 1
    assert await poller.tick() == 0
