"""Proactive 배선 — session.prompt의 Dual-Channel(스텝 4) 통합."""

from __future__ import annotations

import asyncio

import pytest

from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.types import ProactiveMessageEvent
from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy


class StubEngine:
    def __init__(self, frame: ThoughtFrame | None) -> None:
        self._frame = frame

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        return self._frame


def _build_session(fx, engine=None, proactivity_factory=None):
    from jarvis.core.session import AgentSession

    return AgentSession(
        model=fx["model"],
        session_id="test-session",
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory_chain=fx["memory_chain"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
        thought_engine=engine,
        proactivity_factory=proactivity_factory,
    )


def _factory(emit):
    return DefaultProactivityCore(emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5))


@pytest.fixture
def fx(
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
        ThoughtFrame(decision="ask", confidence=0.9, interpretation="먼저 알려줄 게 있어요")
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


async def _noop():
    return None
