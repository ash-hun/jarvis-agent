"""Inner Thought 배선 테스트 — session 삽입 + loop system_prompt 증강."""
from __future__ import annotations

import pytest

from jarvis.agent_layer.loop import _augment_system_prompt
from jarvis.agent_layer.memory.backends.in_memory_ltm import InMemoryLTMBackend
from jarvis.agent_layer.thought import (
    LTMThoughtSink,
    ThoughtFrame,
    ThoughtLog,
    ThoughtRequest,
)
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
from jarvis.agent_layer.types import AgentContext, InnerThoughtEvent
from jarvis.model_layer.types import ModelConfig


class StubEngine:
    """고정 프레임을 반환하는 ThoughtEngine 스텁(LLM 불필요)."""

    def __init__(self, frame: ThoughtFrame | None) -> None:
        self._frame = frame
        self.calls: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.calls.append(request)
        return self._frame


def _build_session(fixtures: dict, engine=None, log=None):
    from jarvis.core.session import AgentSession

    return AgentSession(
        model=fixtures["model"],
        session_id="test-session",
        security_pipeline=fixtures["pipeline"],
        plugin_runner=fixtures["plugin_runner"],
        memory_chain=fixtures["memory_chain"],
        tool_registry=fixtures["tool_registry"],
        skill_registry=fixtures["skill_registry"],
        session_repo=fixtures["repo"],
        thought_engine=engine,
        thought_log=log,
    )


@pytest.fixture
def session_fixtures(
    faux_model,
    permissive_pipeline,
    plugin_runner,
    memory_chain,
    tool_registry,
    skill_registry,
    jsonl_repo,
):
    return {
        "model": faux_model,
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "memory_chain": memory_chain,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }


# ── loop: system_prompt 증강 (순수 함수) ──────────────────────────────────────

def test_augment_appends_composed_prompt():
    ctx = AgentContext(
        session_id="s",
        model=ModelConfig(provider="faux", model="m"),
        system_prompt="기존 프롬프트",
        metadata={"inner_thought_prompt": "[내적 사고]\n해석: 진짜 의도"},
    )
    out = _augment_system_prompt(ctx)
    assert "기존 프롬프트" in out
    assert "[내적 사고]" in out
    assert "진짜 의도" in out


def test_augment_noop_without_prompt():
    ctx = AgentContext(
        session_id="s",
        model=ModelConfig(provider="faux", model="m"),
        system_prompt="P",
        metadata={},
    )
    assert _augment_system_prompt(ctx) == "P"


def test_augment_uses_block_when_no_base_prompt():
    ctx = AgentContext(
        session_id="s",
        model=ModelConfig(provider="faux", model="m"),
        system_prompt=None,
        metadata={"inner_thought_prompt": "[내적 사고] x"},
    )
    assert _augment_system_prompt(ctx) == "[내적 사고] x"


# ── session: think() 삽입 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_emits_inner_thought_event(session_fixtures):
    await session_fixtures["repo"].create(session_id="test-session")
    frame = ThoughtFrame(interpretation="불안함 감지", decision="ask", confidence=0.7)
    engine = StubEngine(frame)
    session = _build_session(session_fixtures, engine=engine)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    await session.prompt("배포 상태 알려줘")

    thought_events = [e for e in events if isinstance(e, InnerThoughtEvent)]
    assert len(thought_events) == 1
    assert thought_events[0].decision == "ask"
    assert thought_events[0].interpretation == "불안함 감지"
    # 엔진은 사용자 입력으로 호출됐다.
    assert engine.calls[0].user_input == "배포 상태 알려줘"


@pytest.mark.asyncio
async def test_session_stores_thought_log(session_fixtures):
    await session_fixtures["repo"].create(session_id="test-session")
    backend = InMemoryLTMBackend()
    engine = StubEngine(ThoughtFrame(interpretation="x", decision="silent", confidence=0.1))
    log = ThoughtLog([LTMThoughtSink(backend)])
    session = _build_session(session_fixtures, engine=engine, log=log)

    await session.prompt("안녕하세요 잘 지내시나요")

    entries = await backend.get_recent(limit=10)
    assert len(entries) == 1
    assert entries[0].source == THOUGHT_SOURCE


@pytest.mark.asyncio
async def test_session_without_engine_emits_no_thought(session_fixtures):
    await session_fixtures["repo"].create(session_id="test-session")
    session = _build_session(session_fixtures, engine=None)

    events: list = []
    session.subscribe(lambda e: events.append(e) or _noop())

    await session.prompt("hello")

    assert not [e for e in events if isinstance(e, InnerThoughtEvent)]


@pytest.mark.asyncio
async def test_session_silent_engine_does_not_break_turn(session_fixtures):
    """엔진이 None(생략/실패)을 반환해도 메인 턴은 정상 완료."""
    await session_fixtures["repo"].create(session_id="test-session")
    engine = StubEngine(None)
    session = _build_session(session_fixtures, engine=engine)

    result = await session.prompt("뭔가 물어봄")
    assert result is not None  # 메인 응답 정상


async def _noop():
    return None
