"""memory 기능의 메모리 범위: 세션 교체, 자식 범위, 작업 범위, 턴 컨텍스트에서 범위 만들기."""

from jarvis.memory.scope import LOCAL_USER, MAIN_AGENT, TASK_AGENT, MemoryScope, scope_from_context, task_scope

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def test_with_session_keeps_owner():
    assert SCOPE.with_session(None) == MemoryScope(user_id="u1", agent_id="main")


def test_child_scope_inherits_user_and_replaces_agent_and_session():
    child = SCOPE.child(agent_id="researcher", session_id="agent_researcher__s1")

    assert child == MemoryScope("u1", "researcher", "agent_researcher__s1")


def test_working_set_requires_exact_match():
    assert SCOPE.same_working_set(MemoryScope("u1", "main", "s1"))
    assert not SCOPE.same_working_set(MemoryScope("u1", "main", "s2"))


def test_task_scope_depends_only_on_user_and_task():
    assert task_scope("u1", "t9") == MemoryScope(user_id="u1", agent_id=TASK_AGENT, session_id="task_t9")
    assert task_scope(None, "t9").user_id == LOCAL_USER


def test_scope_from_context_uses_only_what_the_caller_passed():
    local = scope_from_context({"session_id": "s"})
    explicit = scope_from_context({"user_id": "u2", "agent_id": "a2", "session_id": "s"})

    assert local == MemoryScope(user_id=LOCAL_USER, agent_id=MAIN_AGENT, session_id="s")
    assert explicit == MemoryScope(user_id="u2", agent_id="a2", session_id="s")
