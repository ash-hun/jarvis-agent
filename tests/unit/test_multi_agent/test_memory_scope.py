"""4단계: 위임 시 자식 세션이 부모 범위를 상속하고, 세션이 부모별로 분리되며, 부모가 위임을 기억한다."""

import pytest

from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.core.multi_agent.factory import AgentDefinition, AgentFactory, AgentMemoryPolicy, child_session_id
from jarvis.core.multi_agent.task import AgentTask
from jarvis.core.multi_agent.tool import AgentNodeTool
from jarvis.core.session import AgentSession
from jarvis.memory import MemoryKind, MemoryManager, MemoryScope, current_scope
from jarvis.memory.middleware import MemoryMiddlewareAdapter
from jarvis.memory.stores.in_memory import InMemoryItemStore

PARENT_S1 = MemoryScope(user_id="jh", agent_id="main", session_id="s1")
PARENT_S2 = MemoryScope(user_id="jh", agent_id="main", session_id="s2")


@pytest.fixture
def memory() -> MemoryManager:
    return MemoryManager(InMemoryItemStore())


@pytest.fixture
def harness(memory, faux_model, permissive_pipeline, plugin_runner, tool_registry, skill_registry, jsonl_repo):
    """정의 → 자식 AgentSession 을 만드는 빌더와 팩토리, 도구. 실제 startup 배선과 같은 모양."""
    chain = MemoryMiddlewareChain(stages=[MemoryMiddlewareAdapter(memory)])
    built: dict[str, AgentSession] = {}

    def build_session(definition, session_id: str) -> AgentSession:
        session = AgentSession(
            model=faux_model,
            session_id=session_id,
            security_pipeline=permissive_pipeline,
            plugin_runner=plugin_runner,
            memory_chain=chain,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            session_repo=jsonl_repo,
            agent_name=definition.name,
            inherit_scope=True,
        )
        built[session_id] = session
        return session

    def make(definition: AgentDefinition) -> tuple[AgentNodeTool, AgentFactory]:
        factory = AgentFactory(build_session=build_session, session_repo=jsonl_repo)
        return AgentNodeTool(definition=definition, factory=factory, memory=memory), factory

    return make, built


async def _delegate(tool: AgentNodeTool, parent: MemoryScope, task: str = "논문 3편 요약해줘"):
    token = current_scope.set(parent)  # 부모 턴 안에서 도구가 실행되는 상황
    try:
        return await tool.execute("c1", {"task": task})
    finally:
        current_scope.reset(token)


async def test_child_session_inherits_user_and_gets_its_own_session(harness, faux_model_with_response):
    faux_model_with_response("요약 완료")
    make, built = harness
    tool, factory = make(AgentDefinition(name="researcher", description="리서치"))

    result = await _delegate(tool, PARENT_S1)

    assert not result.is_error and "요약 완료" in result.content[0].text
    child = built["agent_researcher__s1"]
    assert child.memory_scope == MemoryScope(user_id="jh", agent_id="researcher", session_id="agent_researcher__s1")
    assert len(factory) == 1


async def test_parent_scope_is_restored_after_delegation(harness, faux_model_with_response):
    faux_model_with_response("ok")
    make, _ = harness
    tool, _ = make(AgentDefinition(name="researcher", description="리서치"))
    token = current_scope.set(PARENT_S1)
    try:
        await tool.execute("c1", {"task": "x"})
        assert current_scope.get() == PARENT_S1
    finally:
        current_scope.reset(token)


async def test_two_parent_sessions_get_separate_child_sessions_and_histories(
    harness, faux_model_with_response, jsonl_repo
):
    faux_model_with_response("ok")
    make, built = harness
    tool, factory = make(AgentDefinition(name="researcher", description="리서치"))

    await _delegate(tool, PARENT_S1, "첫 부모의 작업")
    await _delegate(tool, PARENT_S2, "둘째 부모의 작업")

    assert set(built) == {"agent_researcher__s1", "agent_researcher__s2"} and len(factory) == 2
    first = [m.content for m in await jsonl_repo.get_messages("agent_researcher__s1") if m.role == "user"]
    second = [m.content for m in await jsonl_repo.get_messages("agent_researcher__s2") if m.role == "user"]
    assert first == ["첫 부모의 작업"] and second == ["둘째 부모의 작업"]


async def test_same_parent_reuses_child_session(harness, faux_model_with_response, jsonl_repo):
    faux_model_with_response("ok")
    make, built = harness
    tool, factory = make(AgentDefinition(name="researcher", description="리서치"))

    await _delegate(tool, PARENT_S1, "작업 1")
    await _delegate(tool, PARENT_S1, "작업 2")

    assert len(built) == 1 and len(factory) == 1
    assert len([m for m in await jsonl_repo.get_messages("agent_researcher__s1") if m.role == "user"]) == 2


async def test_parent_remembers_the_delegation_as_an_episode(harness, memory, faux_model_with_response):
    faux_model_with_response("세 편 요약: A, B, C")
    make, _ = harness
    tool, _ = make(AgentDefinition(name="researcher", description="리서치"))

    await _delegate(tool, PARENT_S1)

    episodes = await memory.recall("위임 researcher", scope=PARENT_S1, kinds=[MemoryKind.EPISODIC])
    assert len(episodes) == 1
    item = episodes[0]
    assert "researcher" in item.content and "논문 3편" in item.content and "세 편 요약" in item.content
    assert (item.source, item.visibility, item.author) == ("delegation", "private", "orchestrator")
    assert item.metadata["success"] is True and "agent:researcher" in item.tags
    # 서브 에이전트 자신은 부모의 위임 기록을 보지 않는다(부모 private)
    child_scope = PARENT_S1.child("researcher", "agent_researcher__s1")
    assert await memory.recall("위임 researcher", scope=child_scope) == []


async def test_subagent_sees_user_shared_facts_but_not_parent_private(harness, memory, faux_model_with_response):
    faux_model_with_response("ok")
    await memory.remember("선호 음료: 커피", source="explicit", scope=PARENT_S1)  # shared
    await memory.remember("세션 요약: 예산 논의", source="auto_summary", scope=PARENT_S1)  # private
    make, built = harness
    tool, _ = make(AgentDefinition(name="researcher", description="리서치"))

    await _delegate(tool, PARENT_S1)

    child_scope = built["agent_researcher__s1"].memory_scope
    assert [i.content for i in await memory.fixed_facts(child_scope)] == ["선호 음료: 커피"]
    assert [i.content for i in await memory.recent(scope=child_scope)] == ["선호 음료: 커피"]
    # 반대로 자식이 남긴 private 요약은 부모에게 안 보인다
    await memory.remember("작업 메모: 논문 요약", source="auto_summary", scope=child_scope)
    assert "작업 메모" not in " ".join(i.content for i in await memory.recent(scope=PARENT_S1))


async def test_per_task_policy_makes_and_removes_a_session_per_delegation(
    harness, faux_model_with_response, jsonl_repo
):
    faux_model_with_response("ok")
    make, built = harness
    defn = AgentDefinition(name="grep", description="검색", memory=AgentMemoryPolicy(stm="per_task"))
    tool, factory = make(defn)

    await _delegate(tool, PARENT_S1, "파일 찾기")
    await _delegate(tool, PARENT_S1, "폴더 찾기")  # 작업마다 세션이 하나씩 생겼다 사라진다

    assert len(factory) == 0
    ids = list(built)
    assert len(ids) == 2 and all(i.startswith("agent_grep__task_") for i in ids)
    assert await jsonl_repo.get_messages(ids[0]) == []  # 끝나면 지워진다


def test_child_session_id_follows_policy():
    task = AgentTask.create("t")
    base = AgentDefinition(name="r", description="d")
    assert child_session_id(base, PARENT_S1, task) == "agent_r__s1"
    per_task = AgentDefinition(name="r", description="d", memory=AgentMemoryPolicy(stm="per_task"))
    assert child_session_id(per_task, PARENT_S1, task) == f"agent_r__task_{task.task_id}"
    per_agent = AgentDefinition(name="r", description="d", memory=AgentMemoryPolicy(stm="per_agent"))
    assert child_session_id(per_agent, PARENT_S1, task) == "agent_r"


def test_memory_policy_rejects_unknown_stm():
    with pytest.raises(ValueError):
        AgentMemoryPolicy(stm="forever")  # type: ignore[arg-type]


def test_loader_parses_memory_block(tmp_path):
    from jarvis.core.multi_agent.loader import load_agent_definitions

    (tmp_path / "a.yaml").write_text(
        "- name: grep\n  description: d\n  memory:\n    stm: per_task\n"
        "- name: bad\n  description: d\n  memory:\n    stm: forever\n"
        "- name: plain\n  description: d\n"
    )
    defs = {d.name: d for d in load_agent_definitions(str(tmp_path))}
    assert defs["grep"].memory.stm == "per_task"
    assert defs["plain"].memory.stm == "per_parent_session"
    assert "bad" not in defs  # 잘못된 정책은 정의 전체를 버린다
