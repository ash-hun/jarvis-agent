"""Protocol 에서 바꾼 core 기본 클래스: 기본 동작과 구현체의 isinstance 가 유지되는지."""

import pytest
import asyncio

from jarvis.core.proactive import (
    AnyTrigger,
    DefaultProactivityCore,
    DefaultProactivityPolicy,
    ExternalTrigger,
    IntervalTrigger,
    ProactiveMessage,
    ProactivityCore,
    ProactivityPolicy,
    ReflectionTrigger,
)
from jarvis.core.external import (
    ExternalEvent,
    ExternalSource,
    ExternalSourceSpec,
    InMemorySeenStore,
    JsonlSeenStore,
    McpToolSource,
    SeenStore,
)
from jarvis.agent_layer.thought.types import ThoughtFrame
from jarvis.config import MCPServerConfig

SPEAKING_FRAME = ThoughtFrame(decision="act", confidence=1.0, utterance="먼저 말할 거리")


async def test_external_source_default_polls_nothing():
    source = ExternalSource("blank", 60.0)
    assert (source.name, source.interval_sec) == ("blank", 60.0)
    assert await source.poll() == []


def test_mcp_source_is_external_source_with_spec_fields():
    spec = ExternalSourceSpec(name="cal", server="gcal", tool="list_events", interval_sec=42.0)
    source = McpToolSource(spec, MCPServerConfig(name="gcal"))
    assert isinstance(source, ExternalSource)
    assert (source.name, source.interval_sec) == ("cal", 42.0)


async def test_seen_store_default_passes_everything_twice():
    store = SeenStore()
    events = [ExternalEvent(source="s", key="s:1")]
    assert await store.filter_new(events) == events
    assert await store.filter_new(events) == events  # 기억하지 않는다


def test_seen_store_implementations_inherit(tmp_path):
    assert isinstance(InMemorySeenStore(), SeenStore)
    assert isinstance(JsonlSeenStore(path=str(tmp_path / "seen.jsonl")), SeenStore)


async def test_reflection_trigger_default_never_fires():
    trigger = ReflectionTrigger()
    trigger.notify_activity()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(trigger.wait(), timeout=0.01)


async def test_default_trigger_does_not_block_any_trigger():
    external = ExternalTrigger()
    external.fire()
    await asyncio.wait_for(AnyTrigger([ReflectionTrigger(), external]).wait(), timeout=1.0)


def test_interval_and_external_triggers_inherit_noop_activity():
    for trigger in (IntervalTrigger(1.0), ExternalTrigger()):
        assert isinstance(trigger, ReflectionTrigger)
        trigger.notify_activity()


def test_policy_default_is_immediate_and_silent():
    policy = ProactivityPolicy()
    assert policy.plan_response(ThoughtFrame(needs_background=True, filler="잠시만")).mode == "immediate"
    assert policy.check_awaiting("s") is None
    policy.note_user_activity("s")
    decision = policy.decide_proactive(SPEAKING_FRAME, session_id="s")
    assert decision.speak is False
    assert decision.reason == "proactivity disabled"
    assert isinstance(DefaultProactivityPolicy(), ProactivityPolicy)


async def test_core_default_runs_main_and_stays_silent():
    core = ProactivityCore()
    calls: list[str] = []

    async def run_main():
        calls.append("main")
        return None

    assert await core.dispatch_request(ThoughtFrame(needs_background=True), run_main) is None
    assert calls == ["main"]
    decision = await core.reflect(SPEAKING_FRAME, session_id="s")
    assert decision.speak is False
    assert core.check_awaiting("s") is None
    core.note_user_activity("s")


def test_default_core_inherits_base():
    async def emit(message: ProactiveMessage) -> None:
        return None

    assert isinstance(DefaultProactivityCore(emit_proactive=emit), ProactivityCore)
