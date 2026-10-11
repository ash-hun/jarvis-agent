"""OrchestrationService, orchestrate 도구, /orchestrate 명령. 실제 AgentSession + faux provider."""

import pytest

from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.agent_layer.memory.memory_adapter import MemoryMiddlewareAdapter
from jarvis.core.multi_agent.factory import AgentDefinition, AgentFactory
from jarvis.core.multi_agent.orchestrate_tool import OrchestrateTool
from jarvis.core.multi_agent.service import PATTERNS, OrchestrationService
from jarvis.core.session import AgentSession
from jarvis.core.slash.orchestrate_cmd import make_orchestrate_handler, parse_args
from jarvis.core.tools.registry import ToolRegistry
from jarvis.memory import MemoryKind, MemoryScope, MemoryService, current_scope
from jarvis.memory.stores.in_memory import InMemoryItemStore

PARENT = MemoryScope(user_id="jh", agent_id="main", session_id="s1")


@pytest.fixture
def memory() -> MemoryService:
    return MemoryService(InMemoryItemStore())


@pytest.fixture
def service(memory, faux_model, permissive_pipeline, plugin_runner, skill_registry, jsonl_repo):
    """startup 과 같은 모양: 메인 레지스트리에 에이전트 도구가 꽂히고, 빌더가 정의별 도구 서브셋을 고른다."""
    from jarvis.core.multi_agent.tool import AgentNodeTool

    chain = MemoryMiddlewareChain(stages=[MemoryMiddlewareAdapter(memory)])
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
            model=faux_model, session_id=session_id, security_pipeline=permissive_pipeline,
            plugin_runner=plugin_runner, memory_chain=chain, tool_registry=registry, skill_registry=skill_registry,
            session_repo=jsonl_repo, agent_name=definition.name, system_prompt=definition.system_prompt,
            inherit_scope=True,
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


async def _run(service, *args, **kw):
    token = current_scope.set(PARENT)  # 메인 턴 안에서 호출되는 상황
    try:
        return await service.run(*args, **kw)
    finally:
        current_scope.reset(token)


# ── 서비스 ────────────────────────────────────────────────────────────────────


async def test_hierarchical_run_records_and_clears_task_memory(service, memory, faux_model_with_response):
    faux_model_with_response("완료")
    result = await _run(service, "hierarchical", "보고서 작성")

    assert result.success and result.agent_name == "hierarchical_orchestrator"
    episodes = await memory.recall("오케스트레이션", scope=PARENT, kinds=[MemoryKind.EPISODIC], limit=10)
    assert episodes and episodes[0].metadata["pattern"] == "hierarchical" and "pattern:hierarchical" in episodes[0].tags
    # 작업이 끝나면 공유 메모리는 비운다
    assert await memory.task_notes(episodes[0].metadata["task_id"], PARENT) == []


async def test_blackboard_promote_writes_shared_facts(service, memory, faux_model_with_response):
    faux_model_with_response("시장은 성장 중")
    await _run(service, "blackboard", "시장 분석", promote=True)
    facts = await memory.recent(scope=MemoryScope(user_id="jh", agent_id="other"), kinds=[MemoryKind.SEMANTIC])
    assert len(facts) == 2 and all(f.source == "promoted" for f in facts)


async def test_market_picks_matching_agent_and_subset(service, faux_model_with_response):
    faux_model_with_response("done")
    result = await _run(service, "market", "보고서 작성 해줘")
    assert result.agent_name == "writer"
    # 범위를 좁혔는데 라벨이 안 맞으면 입찰자가 없다. market 은 억지로 맡기지 않는다
    only_planner = await _run(service, "market", "보고서 작성 해줘", agents=["planner"])
    assert not only_planner.success and "No agent available" in (only_planner.error or "")


async def test_pipeline_pattern_chains_stages(service, faux_model_with_response):
    faux_model_with_response("단계 결과")
    result = await _run(service, "hierarchical,blackboard", "두 단계")
    assert result.success and result.agent_name == "blackboard_orchestrator"


async def test_supervisor_pattern_runs_supervisor_session_with_agent_tools(
    service, faux_model_with_response, jsonl_repo
):
    call = {"id": "c1", "name": "agent_writer", "arguments": {"task": "써"}}
    faux_model_with_response("감독 완료", tool_calls=[call])
    result = await _run(service, "supervisor", "글 하나")
    assert result.success and "감독 완료" in result.content
    # 감독자 세션이 부모 세션 아래 생겼고 그 아래에 writer 세션이 생겼다
    assert await jsonl_repo.get_messages("agent_supervisor__s1")
    assert await jsonl_repo.get_messages("agent_writer__agent_supervisor__s1")


async def test_unknown_pattern_or_agent_raises(service):
    with pytest.raises(ValueError, match="unknown pattern"):
        await _run(service, "swarm", "x")
    with pytest.raises(ValueError, match="unknown agent"):
        await _run(service, "market", "x", agents=["ghost"])


# ── 도구 ──────────────────────────────────────────────────────────────────────


async def test_orchestrate_tool_describes_patterns_and_agents(service, faux_model_with_response):
    faux_model_with_response("ok")
    tool = OrchestrateTool(service)
    assert tool.name == "orchestrate" and set(tool.parameters["properties"]["pattern"]["enum"]) == set(PATTERNS)
    assert "planner" in tool.description and "writer" in tool.description

    token = current_scope.set(PARENT)
    try:
        ok = await tool.execute("c1", {"pattern": "blackboard", "task": "분석"})
        bad = await tool.execute("c2", {"pattern": "nope", "task": "분석"})
    finally:
        current_scope.reset(token)
    assert not ok.is_error and "ok" in ok.content[0].text
    assert bad.is_error and "unknown pattern" in bad.content[0].text


# ── 슬래시 ────────────────────────────────────────────────────────────────────


def test_parse_args_handles_flags_anywhere():
    assert parse_args("blackboard --agents a,b --promote 시장 분석") == ("blackboard", ["a", "b"], True, "시장 분석")
    assert parse_args("Market 날씨 알려줘") == ("market", None, False, "날씨 알려줘")
    with pytest.raises(ValueError):
        parse_args("market")


async def test_slash_handler_list_run_and_errors(service, faux_model_with_response):
    faux_model_with_response("결과물")
    handler = make_orchestrate_handler(service)
    listing = await handler("list")
    assert "hierarchical" in listing and "writer (level 1, 작성, 보고서)" in listing
    assert "[Orchestrate] 사용법" in await handler("")

    token = current_scope.set(PARENT)
    try:
        out = await handler("blackboard 보고서")
        err = await handler("nope 보고서")
    finally:
        current_scope.reset(token)
    assert out.startswith("[Orchestrate] blackboard 완료") and "결과물" in out
    assert err.startswith("[Orchestrate] unknown pattern")


def test_loader_reads_level(tmp_path):
    from jarvis.core.multi_agent.loader import load_agent_definitions

    (tmp_path / "a.yaml").write_text("- name: a\n  description: d\n  level: 2\n- name: b\n  description: d\n")
    defs = {d.name: d.level for d in load_agent_definitions(str(tmp_path))}
    assert defs == {"a": 2, "b": 0}


# ── 도구 컨텍스트: 레지스트리를 거치면 부모 범위가 인자로 온다 ───────────────


async def test_tool_context_carries_parent_scope_without_contextvar(
    service, memory, faux_model_with_response, jsonl_repo
):
    from jarvis.core.tools.registry import ToolContext, ToolRegistry

    faux_model_with_response("ok")
    registry = ToolRegistry()
    registry.register(OrchestrateTool(service))
    parent = MemoryScope(user_id="jh", agent_id="main", session_id="ctx-session")
    assert current_scope.get() is None  # contextvar 없이

    result = await registry.execute("c1", "orchestrate", {"pattern": "blackboard", "task": "분석"},
                                    context=ToolContext(scope=parent, session_id="ctx-session", user_id="jh"))

    assert not result.is_error
    episodes = await memory.recall("오케스트레이션", scope=parent, kinds=[MemoryKind.EPISODIC])
    assert episodes and episodes[0].scope.session_id == "ctx-session"
    assert await jsonl_repo.get_messages("agent_planner__ctx-session")


def test_registry_only_passes_context_to_tools_that_accept_it():
    from jarvis.core.tools.registry import accepts_context

    class Plain:
        async def execute(self, tool_call_id, params, signal=None): ...

    class Aware:
        async def execute(self, tool_call_id, params, signal=None, context=None): ...

    assert accepts_context(Plain()) is False and accepts_context(Aware()) is True


def test_supervisor_prompt_from_string_or_file(tmp_path):
    from jarvis.core.multi_agent.service import load_supervisor_prompt

    assert load_supervisor_prompt("") is None
    assert load_supervisor_prompt("짧게 답하라") == "짧게 답하라"
    f = tmp_path / "sup.md"
    f.write_text("파일에서 읽은 지시문\n")
    assert load_supervisor_prompt(str(f)) == "파일에서 읽은 지시문"
