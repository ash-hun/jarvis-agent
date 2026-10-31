"""usermodel 기능: 세션이 저장된 사용자 모델을 사고 요청에 싣고, 없으면 비워 두는지 검증한다."""

import pytest

from tests.fixtures.openloop_helpers import SESSION_ID, CapturingEngine, build_session, say
from jarvis.agent_layer.usermodel import InMemoryUserModelStore, UserModel


@pytest.fixture
async def fx(faux_model, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo):
    await jsonl_repo.create(session_id=SESSION_ID)
    return {
        "model": faux_model,
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }


async def test_user_model_injected_into_request(fx):
    um_store = InMemoryUserModelStore()
    await um_store.save(UserModel(summary="간결한 답 선호", traits=["Python"]))
    engine = CapturingEngine()
    session = build_session(fx, engine, None, user_model_store=um_store)

    await say(session, "새 입력")

    injected = engine.requests[0].user_model
    assert "[사용자 모델]" in injected
    assert "간결한 답 선호" in injected and "Python" in injected


async def test_user_model_absent_is_blank(fx):
    engine = CapturingEngine()
    session = build_session(fx, engine, None)

    await say(session, "입력")

    assert engine.requests[0].user_model == ""
