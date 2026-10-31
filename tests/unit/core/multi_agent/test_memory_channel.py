"""오케스트레이션 통로: 에이전트 간 결과가 작업 공유 메모리를 거쳐 다음 에이전트의 프롬프트에 실제로 도달한다."""

import pytest
from types import SimpleNamespace

from jarvis.core.multi_agent.orchestrators.hierarchical import HierarchicalOrchestrator
from jarvis.core.multi_agent.orchestrators.blackboard import BlackboardOrchestrator
from jarvis.core.multi_agent.orchestrators.supervisor import SupervisorOrchestrator
from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.memory import MemoryKind, MemoryScope, MemoryService, current_task
from jarvis.core.multi_agent.topologies.blackboard import BlackboardTopology
from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology
from jarvis.core.multi_agent.orchestrators.market import MarketOrchestrator
from jarvis.core.multi_agent.factory import AgentDefinition, AgentFactory
from jarvis.core.multi_agent.node import LazyAgentNode, capability_score
from jarvis.core.multi_agent.blackboard import SharedBlackboard
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.agent_types import AgentLoopConfig
from jarvis.memory.memory_service import TASK_HEADER
from jarvis.core.multi_agent.task import AgentTask
from jarvis.core.session import AgentSession

PARENT = MemoryScope(user_id="jh", agent_id="main", session_id="s1")


@pytest.fixture
def memory() -> MemoryService:
    return MemoryService(InMemoryItemStore())


@pytest.fixture
def captured(memory):
    """세션 id 별로 observe 가 LLM 에 넘긴 메시지를 기록한다. 자식 에이전트가 무엇을 봤는지 확인용."""
    seen: dict[str, list] = {}
    original = memory.observe

    async def recording(messages, context):
        out = await original(messages, context)
        seen.setdefault(context.get("session_id") or "?", []).append(SimpleNamespace(messages=out))
        return out

    def start() -> dict[str, list]:
        memory.observe = recording
        return seen

    yield start
    memory.observe = original


@pytest.fixture
def make_node(memory, faux_model, permissive_pipeline, plugin_runner, tool_registry, skill_registry, jsonl_repo):

    def build_session(definition, session_id: str) -> AgentSession:
        return AgentSession(
            model=faux_model, session_id=session_id, security_pipeline=permissive_pipeline,
            plugin_runner=plugin_runner, memory=memory, tool_registry=tool_registry,
            skill_registry=skill_registry, session_repo=jsonl_repo, agent_name=definition.name, inherit_scope=True,
        )

    factory = AgentFactory(build_session=build_session, session_repo=jsonl_repo)

    def make(name: str, capabilities: list[str] | None = None) -> LazyAgentNode:
        definition = AgentDefinition(name=name, description=name, capabilities=capabilities or [])
        return LazyAgentNode(definition, factory, memory)

    return make


def _injected(contexts: list, header: str) -> list[str]:
    out = []
    for ctx in contexts:
        for m in ctx.messages:
            if m.role == "user" and isinstance(m.content, str) and m.content.startswith(header):
                out.append(m.content)
    return out


# ── Hierarchical: 상위 레벨 결과가 하위 레벨 프롬프트에 들어간다 ───────────────


async def test_hierarchical_passes_results_through_shared_task_memory(
    make_node, memory, captured, faux_model_with_response
):
    faux_model_with_response("계획 완료")
    seen = captured()
    topo = HierarchicalTopology()
    topo.add_node(make_node("planner"), level=0)
    topo.add_node(make_node("executor"), level=1)
    task = AgentTask.create("보고서 작성", scope=PARENT)

    result = await HierarchicalOrchestrator(topo, memory=memory).dispatch(task)

    assert result.success and "계획 완료" in result.content
    blocks = _injected(seen["agent_executor__s1"], TASK_HEADER)
    assert blocks and "[planner] level 0 결과: 계획 완료" in blocks[0]
    assert not _injected(seen["agent_planner__s1"], TASK_HEADER)  # 첫 레벨은 볼 게 없다
    # 부모는 위임 두 건을 일화로 기억한다
    episodes = await memory.recall("위임", scope=PARENT, kinds=[MemoryKind.EPISODIC], limit=10)
    assert {e.metadata["agent"] for e in episodes} == {"planner", "executor"}


# ── Blackboard: 작업 공표와 결과가 공유되고, promote 가 shared 사실로 올린다 ────


async def test_blackboard_shares_and_promotes(make_node, memory, captured, faux_model_with_response):
    faux_model_with_response("분석 결과 A")
    seen = captured()
    topo = BlackboardTopology()
    topo.add_node(make_node("analyst"))
    topo.add_node(make_node("critic"))
    board = SharedBlackboard()
    orch = BlackboardOrchestrator(topo, board, memory=memory)
    task = AgentTask.create("시장 분석", scope=PARENT)

    result = await orch.dispatch(task)

    assert result.success
    notes = await memory.task_notes(task.task_id, PARENT)
    assert notes[0] == "[orchestrator] 작업: 시장 분석"
    assert any(n.startswith("[analyst] 결과:") for n in notes) and any(n.startswith("[critic] 결과:") for n in notes)
    # 병렬 실행이라 서로의 결과는 못 보지만 작업 공표는 둘 다 봤다
    for sid in ("agent_analyst__s1", "agent_critic__s1"):
        assert "[orchestrator] 작업: 시장 분석" in _injected(seen[sid], TASK_HEADER)[0]

    await orch.promote([])
    promoted = [e for e in await memory.recent(scope=PARENT, kinds=[MemoryKind.EPISODIC]) if e.source == "promoted"]
    assert len(promoted) == 2
    assert {p.author for p in promoted} == {"analyst", "critic"}


# ── 작업 공유 메모리는 작업별로 분리된다 ──────────────────────────────────────


async def test_task_notes_are_isolated_per_root_task(memory):
    await memory.share("task-a", "a 의 결과", author="x", scope=PARENT)
    assert await memory.task_notes("task-a", PARENT) == ["[x] a 의 결과"]
    assert await memory.task_notes("task-b", PARENT) == []
    await memory.clear_task("task-a", PARENT)
    assert await memory.task_notes("task-a", PARENT) == []


# ── LazyAgentNode: contextvar 복원과 공유 키 ─────────────────────────────────


async def test_lazy_node_restores_task_and_child_reads_as_the_parent_user(
    make_node, memory, captured, faux_model_with_response
):
    faux_model_with_response("ok")
    seen = captured()
    node = make_node("worker")
    sub = AgentTask.create("하위 작업", parent_task_id="root-1", scope=PARENT)
    await memory.share("root-1", "앞선 결과", author="other", scope=PARENT)
    result = await node.invoke(sub)
    assert result.success
    assert current_task.get() is None
    # 자식 세션은 부모의 사용자로 루트 작업의 공유 메모리를 읽는다
    [sid] = seen
    assert "[other] 앞선 결과" in _injected(seen[sid], TASK_HEADER)[0]


# ── Market: capabilities 토큰 매칭 입찰 ──────────────────────────────────────


def test_capability_score_counts_label_hits():
    task = AgentTask.create("웹 검색 으로 논문 찾기")
    assert capability_score(task, "researcher", ["검색", "논문"]) == 2.0
    assert capability_score(task, "coder", ["코드"]) == 0.0
    assert capability_score(task, "검색", []) == 1.0  # 이름도 라벨


async def test_market_picks_best_capability_match(make_node, memory, faux_model_with_response):
    faux_model_with_response("done")
    topo = SupervisorTopology()
    topo.add_node(make_node("generalist"))  # 라벨 없음: 항상 1.0 으로 입찰
    topo.add_node(make_node("researcher", ["검색", "논문"]))
    topo.add_node(make_node("coder", ["코드"]))

    result = await MarketOrchestrator(topo, memory=memory).dispatch(AgentTask.create("논문 검색 해줘", scope=PARENT))
    assert result.agent_name == "researcher"

    result = await MarketOrchestrator(topo, memory=memory).dispatch(AgentTask.create("날씨 알려줘", scope=PARENT))
    assert result.agent_name == "generalist"  # 라벨이 맞는 쪽이 없으면 범용 에이전트


# ── Supervisor: 실제 세션에 도구를 꽂아 LLM 이 위임한다 ─────────────────────


async def test_supervisor_registers_tools_into_live_session_and_delegates(
    make_node, memory, faux_model_with_response, permissive_pipeline, plugin_runner, tool_registry, skill_registry,
    jsonl_repo,
):
    model = faux_model_with_response(
        "검토 완료", tool_calls=[{"id": "c1", "name": "agent_reviewer", "arguments": {"task": "코드 검토"}}]
    )
    await jsonl_repo.create(session_id="sup")
    supervisor = AgentSession(
        model=model, session_id="sup", security_pipeline=permissive_pipeline, plugin_runner=plugin_runner,
        memory=memory, tool_registry=tool_registry,
        skill_registry=skill_registry, session_repo=jsonl_repo, agent_name="supervisor",
        loop_config=AgentLoopConfig(max_turns=2),
    )
    topo = SupervisorTopology()
    topo.add_node(make_node("reviewer"))
    orch = SupervisorOrchestrator(topo, supervisor, memory=memory)

    result = await orch.dispatch(AgentTask.create("PR 검토", scope=PARENT))

    assert result.success and "검토 완료" in result.content
    assert tool_registry.get("agent_reviewer") is not None
    # 위임이 실제로 일어났다: reviewer 자식 세션이 생겼고 부모(supervisor 세션 범위)가 기록을 가진다
    assert await jsonl_repo.get_messages("agent_reviewer__sup")
    delegations = await memory.recall("위임 reviewer", scope=supervisor.memory_scope, kinds=[MemoryKind.EPISODIC])
    assert delegations and delegations[0].metadata["agent"] == "reviewer"
