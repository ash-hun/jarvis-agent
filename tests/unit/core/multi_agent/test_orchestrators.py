"""Orchestrator 단위 테스트 — 각 패턴의 dispatch 로직 검증."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.core.multi_agent.blackboard import SharedBlackboard
from jarvis.core.multi_agent.orchestrators.blackboard import BlackboardOrchestrator
from jarvis.core.multi_agent.orchestrators.hierarchical import HierarchicalOrchestrator
from jarvis.core.multi_agent.orchestrators.market import Bid, MarketOrchestrator
from jarvis.core.multi_agent.orchestrators.pipeline import OrchestratorPipeline
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from jarvis.core.multi_agent.topologies.blackboard import BlackboardTopology
from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def make_node(name: str, response: str = "ok", success: bool = True) -> MagicMock:
    node = MagicMock()
    node.name = name
    node.capabilities = []

    async def invoke(task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_name=name,
            content=response,
            success=success,
            error=None if success else "forced error",
        )

    node.invoke = invoke
    return node


def make_mock_orchestrator(response: str = "done", success: bool = True) -> MagicMock:
    orch = MagicMock()

    async def dispatch(task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_name="mock",
            content=response,
            success=success,
        )

    orch.dispatch = dispatch
    return orch


# ══════════════════════════════════════════════════════════════════════════════
# HierarchicalOrchestrator
# ══════════════════════════════════════════════════════════════════════════════


class TestHierarchicalOrchestrator:
    @pytest.mark.asyncio
    async def test_level_order_sequential(self):
        """레벨 0 → 1 순서로 실행되어야 한다."""
        call_order: list[str] = []

        def make_tracking_node(name: str, level_label: str) -> MagicMock:
            node = MagicMock()
            node.name = name

            async def invoke(task: AgentTask) -> AgentResult:
                call_order.append(level_label)
                return AgentResult(task_id=task.task_id, agent_name=name, content=level_label)

            node.invoke = invoke
            return node

        topo = HierarchicalTopology()
        topo.add_node(make_tracking_node("ctrl", "level0"), level=0)
        topo.add_node(make_tracking_node("worker", "level1"), level=1, parent="ctrl")

        result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("task"))

        assert call_order == ["level0", "level1"]
        assert result.success

    @pytest.mark.asyncio
    async def test_same_level_parallel(self):
        """동일 레벨 노드는 병렬 실행 — 총 시간 ≈ 단일 노드 시간."""
        topo = HierarchicalTopology()

        def make_slow(name: str, delay: float = 0.05) -> MagicMock:
            node = MagicMock()
            node.name = name

            async def invoke(task: AgentTask) -> AgentResult:
                await asyncio.sleep(delay)
                return AgentResult(task_id=task.task_id, agent_name=name, content=name)

            node.invoke = invoke
            return node

        topo.add_node(make_slow("w1"), level=0)
        topo.add_node(make_slow("w2"), level=0)

        import time

        start = time.monotonic()
        result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("parallel"))
        elapsed = time.monotonic() - start

        assert elapsed < 0.09  # 0.05s * 2 직렬이면 0.10s
        assert result.success

    @pytest.mark.asyncio
    async def test_previous_level_results_in_context(self):
        """레벨 1 노드는 레벨 0의 결과를 context로 받는다."""
        received_context: dict = {}

        def make_context_capturing_node(name: str) -> MagicMock:
            node = MagicMock()
            node.name = name

            async def invoke(task: AgentTask) -> AgentResult:
                received_context.update(task.context)
                return AgentResult(task_id=task.task_id, agent_name=name, content="captured")

            node.invoke = invoke
            return node

        topo = HierarchicalTopology()
        topo.add_node(make_node("ctrl", "plan_output"), level=0)
        topo.add_node(make_context_capturing_node("worker"), level=1, parent="ctrl")

        await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("task"))

        assert "previous_results" in received_context
        assert "plan_output" in received_context["previous_results"]

    @pytest.mark.asyncio
    async def test_empty_topology_returns_failure(self):
        topo = HierarchicalTopology()
        result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("task"))
        assert not result.success

    @pytest.mark.asyncio
    async def test_partial_failure_propagates(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("ok", "ok"), level=0)
        topo.add_node(make_node("broken", "err", success=False), level=0)

        result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("task"))
        assert not result.success


# ══════════════════════════════════════════════════════════════════════════════
# MarketOrchestrator
# ══════════════════════════════════════════════════════════════════════════════


class TestMarketOrchestrator:
    @pytest.mark.asyncio
    async def test_selects_capable_agent(self):
        topo = SupervisorTopology()

        incapable = MagicMock()
        incapable.name = "incapable"
        incapable.can_handle = AsyncMock(return_value=False)

        capable = MagicMock()
        capable.name = "capable"
        capable.can_handle = AsyncMock(return_value=True)

        async def invoke(task):
            return AgentResult(task_id=task.task_id, agent_name="capable", content="done")

        capable.invoke = invoke
        topo.add_node(incapable)
        topo.add_node(capable)

        result = await MarketOrchestrator(topo).dispatch(AgentTask.create("task"))
        assert result.success
        assert result.agent_name == "capable"

    @pytest.mark.asyncio
    async def test_no_capable_agent_returns_failure(self):
        topo = SupervisorTopology()
        for name in ("a", "b"):
            node = MagicMock()
            node.name = name
            node.can_handle = AsyncMock(return_value=False)
            topo.add_node(node)

        result = await MarketOrchestrator(topo).dispatch(AgentTask.create("task"))
        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_highest_priority_wins(self):
        topo = SupervisorTopology()

        low = MagicMock()
        low.name = "low"
        low.can_handle = AsyncMock(return_value=True)

        async def invoke_low(task):
            return AgentResult(task_id=task.task_id, agent_name="low", content="low_result")

        low.invoke = invoke_low

        high = MagicMock()
        high.name = "high"
        high.can_handle = AsyncMock(return_value=True)

        async def invoke_high(task):
            return AgentResult(task_id=task.task_id, agent_name="high", content="high_result")

        high.invoke = invoke_high

        topo.add_node(low)
        topo.add_node(high)

        orchestrator = MarketOrchestrator(topo)

        # _collect_bids 오버라이드로 priority 주입
        async def mock_bids(task):
            return [
                Bid(node=low, can_handle=True, priority=0.3),
                Bid(node=high, can_handle=True, priority=0.9),
            ]

        orchestrator._collect_bids = mock_bids

        result = await orchestrator.dispatch(AgentTask.create("task"))
        assert result.content == "high_result"

    @pytest.mark.asyncio
    async def test_empty_topology_returns_failure(self):
        result = await MarketOrchestrator(SupervisorTopology()).dispatch(
            AgentTask.create("task")
        )
        assert not result.success


# ══════════════════════════════════════════════════════════════════════════════
# BlackboardOrchestrator
# ══════════════════════════════════════════════════════════════════════════════


class TestBlackboardOrchestrator:
    @pytest.mark.asyncio
    async def test_writes_task_to_blackboard(self):
        bb = SharedBlackboard()
        topo = BlackboardTopology()
        topo.add_node(make_node("a", "done"))

        await BlackboardOrchestrator(topo, bb).dispatch(AgentTask.create("my task"))

        assert bb.read("task") == "my task"

    @pytest.mark.asyncio
    async def test_writes_results_to_blackboard(self):
        bb = SharedBlackboard()
        topo = BlackboardTopology()
        topo.add_node(make_node("researcher", "research_output"))

        await BlackboardOrchestrator(topo, bb).dispatch(AgentTask.create("task"))

        assert bb.read("result_researcher") == "research_output"

    @pytest.mark.asyncio
    async def test_injects_snapshot_into_context(self):
        received_context: dict = {}
        bb = SharedBlackboard()
        await bb.write("prior_data", "existing", author="system")

        topo = BlackboardTopology()
        node = MagicMock()
        node.name = "solver"

        async def invoke(task: AgentTask) -> AgentResult:
            received_context.update(task.context)
            return AgentResult(task_id=task.task_id, agent_name="solver", content="solved")

        node.invoke = invoke
        topo.add_node(node)

        await BlackboardOrchestrator(topo, bb).dispatch(AgentTask.create("task"))

        assert "blackboard" in received_context
        assert received_context["blackboard"].get("prior_data") == "existing"

    @pytest.mark.asyncio
    async def test_failed_nodes_not_written_to_blackboard(self):
        bb = SharedBlackboard()
        topo = BlackboardTopology()
        topo.add_node(make_node("broken", "err", success=False))

        await BlackboardOrchestrator(topo, bb).dispatch(AgentTask.create("task"))

        assert bb.read("result_broken") is None

    @pytest.mark.asyncio
    async def test_empty_topology_returns_failure(self):
        result = await BlackboardOrchestrator(
            BlackboardTopology(), SharedBlackboard()
        ).dispatch(AgentTask.create("task"))
        assert not result.success


# ══════════════════════════════════════════════════════════════════════════════
# OrchestratorPipeline
# ══════════════════════════════════════════════════════════════════════════════


class TestOrchestratorPipeline:
    @pytest.mark.asyncio
    async def test_sequential_content_passing(self):
        """각 단계 출력이 다음 단계 입력(content)이 된다."""
        received: list[str] = []

        def tracking_orch(response: str) -> MagicMock:
            orch = MagicMock()

            async def dispatch(task: AgentTask) -> AgentResult:
                received.append(task.content)
                return AgentResult(task_id=task.task_id, agent_name="m", content=response)

            orch.dispatch = dispatch
            return orch

        pipeline = OrchestratorPipeline([
            tracking_orch("stage1_out"),
            tracking_orch("stage2_out"),
        ])

        await pipeline.dispatch(AgentTask.create("initial"))

        assert received[0] == "initial"
        assert received[1] == "stage1_out"

    @pytest.mark.asyncio
    async def test_fail_fast_stops_pipeline(self):
        called: list[str] = []

        def failing() -> MagicMock:
            orch = MagicMock()

            async def dispatch(task):
                called.append("fail")
                return AgentResult(task_id=task.task_id, agent_name="m", content="", success=False, error="boom")

            orch.dispatch = dispatch
            return orch

        def succeeding() -> MagicMock:
            orch = MagicMock()

            async def dispatch(task):
                called.append("success")
                return AgentResult(task_id=task.task_id, agent_name="m", content="ok")

            orch.dispatch = dispatch
            return orch

        pipeline = OrchestratorPipeline([failing(), succeeding()])
        result = await pipeline.dispatch(AgentTask.create("task"))

        assert not result.success
        assert "success" not in called

    @pytest.mark.asyncio
    async def test_single_stage(self):
        pipeline = OrchestratorPipeline([make_mock_orchestrator("done")])
        result = await pipeline.dispatch(AgentTask.create("task"))
        assert result.content == "done"
        assert result.success

    def test_empty_pipeline_raises(self):
        with pytest.raises(ValueError):
            OrchestratorPipeline([])

    @pytest.mark.asyncio
    async def test_original_parent_id_preserved(self):
        """파이프라인 내 중간 task들도 원본 task_id를 parent로 유지."""
        parent_ids: list[str | None] = []

        def capturing_orch() -> MagicMock:
            orch = MagicMock()

            async def dispatch(task: AgentTask) -> AgentResult:
                parent_ids.append(task.parent_task_id)
                return AgentResult(task_id=task.task_id, agent_name="m", content="ok")

            orch.dispatch = dispatch
            return orch

        pipeline = OrchestratorPipeline([capturing_orch(), capturing_orch()])
        original = AgentTask.create("original")
        await pipeline.dispatch(original)

        # 1단계: original task 자신 (parent_id=None)
        assert parent_ids[0] is None
        # 2단계: parent_id = original.task_id
        assert parent_ids[1] == original.task_id

    @pytest.mark.asyncio
    async def test_three_stage_pattern_combination(self):
        """Hierarchical → Blackboard → Supervisor 패턴 조합 시뮬레이션."""
        pipeline = OrchestratorPipeline([
            make_mock_orchestrator("plan"),
            make_mock_orchestrator("execute"),
            make_mock_orchestrator("validate"),
        ])
        result = await pipeline.dispatch(AgentTask.create("complex task"))
        assert result.content == "validate"
        assert result.success
