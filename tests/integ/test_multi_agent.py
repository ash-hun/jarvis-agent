"""multi_agent: 실제 AgentSession 으로 위임, 네 패턴, orchestrate 도구, /orchestrate 의 메모리 흐름을 검증한다."""

import pytest
from types import SimpleNamespace

from jarvis.core.multi_agent.factory import AgentDefinition, AgentFactory, AgentMemoryPolicy
from jarvis.core.multi_agent.orchestrators.hierarchical import HierarchicalOrchestrator
from jarvis.core.multi_agent.multi_agent_service import PATTERNS, OrchestrationService
from jarvis.core.multi_agent.orchestrators.blackboard import BlackboardOrchestrator
from jarvis.core.multi_agent.orchestrators.supervisor import SupervisorOrchestrator
from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.memory import MemoryKind, MemoryScope, MemoryService, current_task
from jarvis.core.multi_agent.topologies.blackboard import BlackboardTopology
from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology
from jarvis.core.multi_agent.orchestrators.market import MarketOrchestrator
from jarvis.core.slash.orchestrate_cmd import make_orchestrate_handler
from jarvis.core.tools.tools_registry import ToolContext, ToolRegistry
from jarvis.core.multi_agent.orchestrate_tool import OrchestrateTool
from jarvis.core.multi_agent.blackboard import SharedBlackboard
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.agent_types import AgentLoopConfig
from jarvis.core.multi_agent.node import LazyAgentNode
from jarvis.core.multi_agent.tool import AgentNodeTool
from jarvis.memory.memory_service import TASK_HEADER
from jarvis.core.multi_agent.task import AgentTask
from jarvis.core.session import AgentSession

PARENT = MemoryScope(user_id="jh", agent_id="main", session_id="s1")
PARENT_S2 = MemoryScope(user_id="jh", agent_id="main", session_id="s2")


@pytest.fixture
def memory() -> MemoryService:
    return MemoryService(InMemoryItemStore())


@pytest.fixture
def session_kwargs(memory, permissive_pipeline, plugin_runner, skill_registry, jsonl_repo):
    return dict(
        security_pipeline=permissive_pipeline, plugin_runner=plugin_runner, memory=memory,
        skill_registry=skill_registry, session_repo=jsonl_repo,
    )


@pytest.fixture
def harness(faux_model, tool_registry, jsonl_repo, session_kwargs):
    """startup 배선과 같은 모양: 정의마다 부모 범위를 물려받는 자식 AgentSession 을 만들고 기록한다."""
    built: dict[str, AgentSession] = {}

    def build_session(definition, session_id: str) -> AgentSession:
        session = AgentSession(
            model=faux_model, session_id=session_id, tool_registry=tool_registry, agent_name=definition.name,
            inherit_scope=True, **session_kwargs,
        )
        built[session_id] = session
        return session

    def factory() -> AgentFactory:
        return AgentFactory(build_session=build_session, session_repo=jsonl_repo)

    return SimpleNamespace(built=built, factory=factory)


@pytest.fixture
def make_node(harness, memory):
    factory = harness.factory()

    def make(name: str, capabilities: list[str] | None = None) -> LazyAgentNode:
        definition = AgentDefinition(name=name, description=name, capabilities=capabilities or [])
        return LazyAgentNode(definition, factory, memory)

    return make


@pytest.fixture
def make_tool(harness, memory):
    def make(definition: AgentDefinition) -> tuple[AgentNodeTool, AgentFactory]:
        factory = harness.factory()
        return AgentNodeTool(definition=definition, factory=factory, memory=memory), factory

    return make


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
def service(memory, faux_model, jsonl_repo, session_kwargs):
    """startup 과 같은 모양: 메인 레지스트리에 에이전트 도구가 꽂히고, 빌더가 정의별 도구 서브셋을 고른다."""
    main_registry = ToolRegistry()

    def build_session(definition, session_id: str) -> AgentSession:
        if definition.tools:
            registry = ToolRegistry()
            for name in definition.tools:
                tool = main_registry.get(name)
                if tool is not None:
                    registry.register(tool)
        else:
            registry = main_registry
        return AgentSession(
            model=faux_model, session_id=session_id, tool_registry=registry, agent_name=definition.name,
            system_prompt=definition.system_prompt, inherit_scope=True, **session_kwargs,
        )

    factory = AgentFactory(build_session=build_session, session_repo=jsonl_repo)
    definitions = [
        AgentDefinition(name="planner", description="계획", capabilities=["계획"], level=0),
        AgentDefinition(name="writer", description="작성", capabilities=["작성", "보고서"], level=1),
    ]
    for d in definitions:
        main_registry.register(AgentNodeTool(definition=d, factory=factory, memory=memory))
    svc = OrchestrationService(definitions, factory, memory)
    main_registry.register(OrchestrateTool(svc))
    return svc


def _injected(contexts: list, header: str) -> list[str]:
    out = []
    for ctx in contexts:
        for m in ctx.messages:
            if m.role == "user" and isinstance(m.content, str) and m.content.startswith(header):
                out.append(m.content)
    return out


async def _delegate(tool: AgentNodeTool, parent: MemoryScope, task: str = "논문 3편 요약해줘"):
    return await tool.execute("c1", {"task": task}, context=ToolContext(scope=parent, session_id=parent.session_id))


async def _user_messages(repo, session_id: str) -> list[str]:
    return [m.content for m in await repo.get_messages(session_id) if m.role == "user"]


async def _run(service, *args, **kw):
    return await service.run(*args, parent_scope=PARENT, **kw)


async def test_delegation_child_inherits_user_and_gets_own_session(make_tool, harness, faux_model_with_response):
    faux_model_with_response("요약 완료")
    tool, factory = make_tool(AgentDefinition(name="researcher", description="리서치"))

    result = await _delegate(tool, PARENT)

    assert not result.is_error and "요약 완료" in result.content[0].text
    child = harness.built["agent_researcher__s1"]
    assert child.memory_scope == MemoryScope(user_id="jh", agent_id="researcher", session_id="agent_researcher__s1")
    assert len(factory) == 1


async def test_delegation_separates_child_sessions_per_parent_and_reuses_within_one(
    make_tool, harness, faux_model_with_response, jsonl_repo
):
    faux_model_with_response("ok")
    tool, factory = make_tool(AgentDefinition(name="researcher", description="리서치"))

    await _delegate(tool, PARENT, "작업 1")
    await _delegate(tool, PARENT, "작업 2")
    await _delegate(tool, PARENT_S2, "둘째 부모의 작업")

    assert set(harness.built) == {"agent_researcher__s1", "agent_researcher__s2"} and len(factory) == 2
    assert await _user_messages(jsonl_repo, "agent_researcher__s1") == ["작업 1", "작업 2"]
    assert await _user_messages(jsonl_repo, "agent_researcher__s2") == ["둘째 부모의 작업"]


async def test_delegation_is_remembered_by_parent_only(make_tool, memory, faux_model_with_response):
    faux_model_with_response("세 편 요약: A, B, C")
    tool, _ = make_tool(AgentDefinition(name="researcher", description="리서치"))

    await _delegate(tool, PARENT)

    episodes = await memory.recall("위임 researcher", scope=PARENT, kinds=[MemoryKind.EPISODIC])
    assert len(episodes) == 1
    item = episodes[0]
    assert "researcher" in item.content and "논문 3편" in item.content and "세 편 요약" in item.content
    assert (item.source, item.kind, item.author) == ("delegation", MemoryKind.EPISODIC, "orchestrator")
    assert item.metadata["success"] is True and "agent:researcher" in item.tags
    child_scope = PARENT.child("researcher", "agent_researcher__s1")
    assert await memory.recall("위임 researcher", scope=child_scope) == []


async def test_delegation_child_sees_user_facts_but_not_parent_private(
    make_tool, harness, memory, faux_model_with_response
):
    faux_model_with_response("ok")
    await memory.remember("선호 음료: 커피", source="explicit", scope=PARENT)
    await memory.remember("세션 요약: 예산 논의", source="manual_compact", scope=PARENT)
    tool, _ = make_tool(AgentDefinition(name="researcher", description="리서치"))

    await _delegate(tool, PARENT)

    child_scope = harness.built["agent_researcher__s1"].memory_scope
    assert [i.content for i in await memory.fixed_facts(child_scope)] == ["선호 음료: 커피"]
    seen = [i.content for i in await memory.recent(scope=child_scope)]
    assert "선호 음료: 커피" in seen and "세션 요약: 예산 논의" not in seen
    await memory.remember("작업 메모: 논문 요약", source="manual_compact", scope=child_scope)
    assert "작업 메모" not in " ".join(i.content for i in await memory.recent(scope=PARENT))


async def test_delegation_per_task_policy_creates_and_removes_session_each_time(
    make_tool, harness, faux_model_with_response, jsonl_repo
):
    faux_model_with_response("ok")
    defn = AgentDefinition(name="grep", description="검색", memory=AgentMemoryPolicy(stm="per_task"))
    tool, factory = make_tool(defn)

    await _delegate(tool, PARENT, "파일 찾기")
    await _delegate(tool, PARENT, "폴더 찾기")

    assert len(factory) == 0
    ids = list(harness.built)
    assert len(ids) == 2 and all(i.startswith("agent_grep__task_") for i in ids)
    assert await jsonl_repo.get_messages(ids[0]) == []


async def test_lazy_node_restores_task_and_child_reads_root_task_notes(
    make_node, memory, captured, faux_model_with_response
):
    faux_model_with_response("ok")
    seen = captured()
    await memory.share("root-1", "앞선 결과", author="other", scope=PARENT)

    result = await make_node("worker").invoke(AgentTask.create("하위 작업", parent_task_id="root-1", scope=PARENT))

    assert result.success
    assert current_task.get() is None
    [sid] = seen
    assert "[other] 앞선 결과" in _injected(seen[sid], TASK_HEADER)[0]


async def test_task_notes_are_isolated_per_root_task(memory):
    await memory.share("task-a", "a 의 결과", author="x", scope=PARENT)

    assert await memory.task_notes("task-a", PARENT) == ["[x] a 의 결과"]
    assert await memory.task_notes("task-b", PARENT) == []
    await memory.clear_task("task-a", PARENT)
    assert await memory.task_notes("task-a", PARENT) == []


async def test_hierarchical_passes_results_through_shared_task_memory(
    make_node, memory, captured, faux_model_with_response
):
    faux_model_with_response("계획 완료")
    seen = captured()
    topo = HierarchicalTopology()
    topo.add_node(make_node("planner"), level=0)
    topo.add_node(make_node("executor"), level=1)

    result = await HierarchicalOrchestrator(topo, memory=memory).dispatch(AgentTask.create("보고서 작성", scope=PARENT))

    assert result.success and "계획 완료" in result.content
    blocks = _injected(seen["agent_executor__s1"], TASK_HEADER)
    assert blocks and "[planner] level 0 결과: 계획 완료" in blocks[0]
    assert not _injected(seen["agent_planner__s1"], TASK_HEADER)
    episodes = await memory.recall("위임", scope=PARENT, kinds=[MemoryKind.EPISODIC], limit=10)
    assert {e.metadata["agent"] for e in episodes} == {"planner", "executor"}


async def test_blackboard_shares_task_and_results_and_promotes(make_node, memory, captured, faux_model_with_response):
    faux_model_with_response("분석 결과 A")
    seen = captured()
    topo = BlackboardTopology()
    topo.add_node(make_node("analyst"))
    topo.add_node(make_node("critic"))
    orch = BlackboardOrchestrator(topo, SharedBlackboard(), memory=memory)
    task = AgentTask.create("시장 분석", scope=PARENT)

    result = await orch.dispatch(task)

    assert result.success
    notes = await memory.task_notes(task.task_id, PARENT)
    assert notes[0] == "[orchestrator] 작업: 시장 분석"
    assert any(n.startswith("[analyst] 결과:") for n in notes) and any(n.startswith("[critic] 결과:") for n in notes)
    for sid in ("agent_analyst__s1", "agent_critic__s1"):
        assert "[orchestrator] 작업: 시장 분석" in _injected(seen[sid], TASK_HEADER)[0]

    await orch.promote([])

    promoted = [e for e in await memory.recent(scope=PARENT, kinds=[MemoryKind.EPISODIC]) if e.source == "promoted"]
    assert len(promoted) == 2
    assert {p.author for p in promoted} == {"analyst", "critic"}


async def test_market_picks_best_capability_match_or_generalist(make_node, memory, faux_model_with_response):
    faux_model_with_response("done")
    topo = SupervisorTopology()
    topo.add_node(make_node("generalist"))
    topo.add_node(make_node("researcher", ["검색", "논문"]))
    topo.add_node(make_node("coder", ["코드"]))

    matched = await MarketOrchestrator(topo, memory=memory).dispatch(AgentTask.create("논문 검색 해줘", scope=PARENT))
    unmatched = await MarketOrchestrator(topo, memory=memory).dispatch(AgentTask.create("날씨 알려줘", scope=PARENT))

    assert matched.agent_name == "researcher"
    assert unmatched.agent_name == "generalist"


async def test_supervisor_registers_tools_into_live_session_and_delegates(
    make_node, memory, faux_model_with_response, tool_registry, jsonl_repo, session_kwargs
):
    model = faux_model_with_response(
        "검토 완료", tool_calls=[{"id": "c1", "name": "agent_reviewer", "arguments": {"task": "코드 검토"}}]
    )
    await jsonl_repo.create(session_id="sup")
    supervisor = AgentSession(
        model=model, session_id="sup", tool_registry=tool_registry, agent_name="supervisor",
        loop_config=AgentLoopConfig(max_turns=2), **session_kwargs,
    )
    topo = SupervisorTopology()
    topo.add_node(make_node("reviewer"))

    result = await SupervisorOrchestrator(topo, supervisor, memory=memory).dispatch(
        AgentTask.create("PR 검토", scope=PARENT)
    )

    assert result.success and "검토 완료" in result.content
    assert tool_registry.get("agent_reviewer") is not None
    assert await jsonl_repo.get_messages("agent_reviewer__sup")
    delegations = await memory.recall("위임 reviewer", scope=supervisor.memory_scope, kinds=[MemoryKind.EPISODIC])
    assert delegations and delegations[0].metadata["agent"] == "reviewer"


async def test_service_hierarchical_run_records_and_clears_task_memory(service, memory, faux_model_with_response):
    faux_model_with_response("완료")

    result = await _run(service, "hierarchical", "보고서 작성")

    assert result.success and result.agent_name == "hierarchical_orchestrator"
    episodes = await memory.recall("오케스트레이션", scope=PARENT, kinds=[MemoryKind.EPISODIC], limit=10)
    assert episodes and episodes[0].metadata["pattern"] == "hierarchical" and "pattern:hierarchical" in episodes[0].tags
    assert await memory.task_notes(episodes[0].metadata["task_id"], PARENT) == []


async def test_service_blackboard_promote_writes_parent_episodes_not_user_facts(
    service, memory, faux_model_with_response
):
    """올린 결과는 맡긴 쪽(부모)의 EDM 이다. 다른 에이전트는 정책이 허락할 때만 읽는다."""
    faux_model_with_response("시장은 성장 중")

    await _run(service, "blackboard", "시장 분석", promote=True)

    episodes = await memory.recent(scope=PARENT, kinds=[MemoryKind.EPISODIC])
    assert len([e for e in episodes if e.source == "promoted"]) == 2
    assert await memory.recent(scope=PARENT, kinds=[MemoryKind.SEMANTIC]) == []
    other = MemoryScope(user_id="jh", agent_id="other")
    assert [e for e in await memory.recent(scope=other, kinds=[MemoryKind.EPISODIC]) if e.source == "promoted"] == []


async def test_service_market_picks_matching_agent_and_respects_subset(service, faux_model_with_response):
    faux_model_with_response("done")

    result = await _run(service, "market", "보고서 작성 해줘")
    only_planner = await _run(service, "market", "보고서 작성 해줘", agents=["planner"])

    assert result.agent_name == "writer"
    assert not only_planner.success and "No agent available" in (only_planner.error or "")


async def test_service_pipeline_pattern_chains_stages(service, faux_model_with_response):
    faux_model_with_response("단계 결과")

    result = await _run(service, "hierarchical,blackboard", "두 단계")

    assert result.success and result.agent_name == "blackboard_orchestrator"


async def test_service_supervisor_runs_supervisor_session_with_agent_tools(
    service, faux_model_with_response, jsonl_repo
):
    call = {"id": "c1", "name": "agent_writer", "arguments": {"task": "써"}}
    faux_model_with_response("감독 완료", tool_calls=[call])

    result = await _run(service, "supervisor", "글 하나")

    assert result.success and "감독 완료" in result.content
    assert await jsonl_repo.get_messages("agent_supervisor__s1")
    assert await jsonl_repo.get_messages("agent_writer__agent_supervisor__s1")


async def test_service_unknown_pattern_or_agent_raises(service):
    with pytest.raises(ValueError, match="unknown pattern"):
        await _run(service, "swarm", "x")
    with pytest.raises(ValueError, match="unknown agent"):
        await _run(service, "market", "x", agents=["ghost"])


async def test_orchestrate_tool_describes_patterns_and_reports_errors(service, faux_model_with_response):
    faux_model_with_response("ok")
    tool = OrchestrateTool(service)
    context = ToolContext(scope=PARENT)

    ok = await tool.execute("c1", {"pattern": "blackboard", "task": "분석"}, context=context)
    bad = await tool.execute("c2", {"pattern": "nope", "task": "분석"}, context=context)

    assert tool.name == "orchestrate" and set(tool.parameters["properties"]["pattern"]["enum"]) == set(PATTERNS)
    assert "planner" in tool.description and "writer" in tool.description
    assert not ok.is_error and "ok" in ok.content[0].text
    assert bad.is_error and "unknown pattern" in bad.content[0].text


async def test_orchestrate_tool_via_registry_gets_parent_scope_from_context(
    service, memory, faux_model_with_response, jsonl_repo
):
    faux_model_with_response("ok")
    registry = ToolRegistry()
    registry.register(OrchestrateTool(service))
    parent = MemoryScope(user_id="jh", agent_id="main", session_id="ctx-session")

    result = await registry.execute(
        "c1", "orchestrate", {"pattern": "blackboard", "task": "분석"},
        context=ToolContext(scope=parent, session_id="ctx-session", user_id="jh"),
    )

    assert not result.is_error
    episodes = await memory.recall("오케스트레이션", scope=parent, kinds=[MemoryKind.EPISODIC])
    assert episodes and episodes[0].scope.session_id == "ctx-session"
    assert await jsonl_repo.get_messages("agent_planner__ctx-session")


async def test_orchestrate_slash_lists_runs_and_reports_errors(service, faux_model_with_response):
    faux_model_with_response("결과물")
    handler = make_orchestrate_handler(service)

    listing = await handler("list", PARENT)
    usage = await handler("", PARENT)
    out = await handler("blackboard 보고서", PARENT)
    err = await handler("nope 보고서", PARENT)

    assert "hierarchical" in listing and "writer (level 1, 작성, 보고서)" in listing
    assert "[Orchestrate] 사용법" in usage
    assert out.startswith("[Orchestrate] blackboard 완료") and "결과물" in out
    assert err.startswith("[Orchestrate] unknown pattern")
