"""Open-loop session 배선 — 감지 저장 + 회상 주입 (Tier 2 C1)."""
from __future__ import annotations

import pytest

from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, OpenLoop
from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest


class CapturingEngine:
    """프레임을 반환하고, 받은 ThoughtRequest를 기록하는 스텁."""

    def __init__(self, frame: ThoughtFrame) -> None:
        self._frame = frame
        self.requests: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        return self._frame


def _build_session(fx, engine, store, user_model_store=None):
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
        openloop_store=store,
        user_model_store=user_model_store,
    )


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
async def test_detected_open_loops_are_persisted(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    engine = CapturingEngine(ThoughtFrame(open_loops=["내일 배포 결과 공유", "리뷰 답변"]))
    session = _build_session(fx, engine, store)

    await session.prompt("배포 끝나면 알려줄게")

    loops = await store.list_open(session_id="test-session")
    descs = {x.description for x in loops}
    assert descs == {"내일 배포 결과 공유", "리뷰 답변"}
    assert all(x.origin_session == "test-session" for x in loops)


@pytest.mark.asyncio
async def test_open_loops_deduped_across_turns(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    engine = CapturingEngine(ThoughtFrame(open_loops=["같은 약속"]))
    session = _build_session(fx, engine, store)

    await session.prompt("첫 턴")
    await session.prompt("둘째 턴")  # 같은 open_loop 재감지

    assert len(await store.list_open()) == 1  # 중복 저장 안 됨


@pytest.mark.asyncio
async def test_existing_open_loops_recalled_into_request(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    await store.add(OpenLoop(description="기존 약속 A", origin_session="test-session"))
    engine = CapturingEngine(ThoughtFrame())
    session = _build_session(fx, engine, store)

    await session.prompt("새 입력")

    # 엔진에 전달된 ThoughtRequest.open_loops에 기존 항목이 주입됐다.
    assert engine.requests[0].open_loops == ["기존 약속 A"]


@pytest.mark.asyncio
async def test_no_store_is_noop(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CapturingEngine(ThoughtFrame(open_loops=["무시됨"]))
    session = _build_session(fx, engine, store=None)

    result = await session.prompt("입력")
    assert result is not None  # store 없어도 정상 동작
    assert engine.requests[0].open_loops == []


@pytest.mark.asyncio
async def test_user_model_injected_into_request(fx):
    from jarvis.agent_layer.usermodel import InMemoryUserModelStore, UserModel

    await fx["repo"].create(session_id="test-session")
    um_store = InMemoryUserModelStore()
    await um_store.save(UserModel(summary="간결한 답 선호", traits=["Python"]))
    engine = CapturingEngine(ThoughtFrame())
    session = _build_session(fx, engine, store=None, user_model_store=um_store)

    await session.prompt("새 입력")

    injected = engine.requests[0].user_model
    assert "[사용자 모델]" in injected
    assert "간결한 답 선호" in injected and "Python" in injected


@pytest.mark.asyncio
async def test_user_model_absent_is_blank(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CapturingEngine(ThoughtFrame())
    session = _build_session(fx, engine, store=None, user_model_store=None)

    await session.prompt("입력")
    assert engine.requests[0].user_model == ""
