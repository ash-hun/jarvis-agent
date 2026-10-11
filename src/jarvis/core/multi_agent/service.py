"""[core] 패턴 이름과 작업 문구로 토폴로지와 오케스트레이터를 조립해 실행하는 슬래시 명령과 도구의 공통 뒷단."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope, current_task

from .blackboard import SharedBlackboard
from .factory import AgentDefinition, AgentFactory
from .node import LazyAgentNode, _clip
from .orchestrators.base import BaseOrchestrator
from .orchestrators.blackboard import BlackboardOrchestrator
from .orchestrators.hierarchical import HierarchicalOrchestrator
from .orchestrators.market import MarketOrchestrator
from .orchestrators.pipeline import OrchestratorPipeline
from .orchestrators.supervisor import SupervisorOrchestrator
from .protocol import OrchestratorProtocol
from .task import AgentResult, AgentTask
from .topologies.blackboard import BlackboardTopology
from .topologies.hierarchical import HierarchicalTopology
from .topologies.supervisor import SupervisorTopology

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService

PATTERNS: dict[str, str] = {
    "supervisor": "LLM 감독자가 어느 에이전트를 언제 부를지 스스로 정한다. 판단이 필요한 열린 작업",
    "hierarchical": "level 순서대로, 같은 level 은 병렬. 앞 level 결과가 뒤 level 에 전달된다. 계획 → 실행 → 검토",
    "market": "작업 문구와 capabilities 가 맞는 에이전트 하나가 맡는다. 전문 분야가 뚜렷한 단일 작업",
    "blackboard": "모든 에이전트가 같은 작업을 병렬로 보고 결과를 모은다. 다각도 분석, 브레인스토밍",
}
SUPERVISOR_PROMPT = (
    "당신은 감독자다. 아래 서브 에이전트 도구를 써서 작업을 나눠 맡기고, 결과를 모아 최종 답을 한 번에 정리하라. "
    "직접 할 수 있는 일도 적절한 에이전트가 있으면 맡겨라."
)
ORCHESTRATION_SOURCE = "delegation"


class OrchestrationService:
    def __init__(
        self,
        definitions: Sequence[AgentDefinition],
        factory: AgentFactory,
        memory: MemoryService | None = None,
        supervisor_prompt: str | None = None,
    ) -> None:
        self._definitions = {d.name: d for d in definitions}
        self._factory = factory
        self._memory = memory
        self._supervisor_prompt = supervisor_prompt or SUPERVISOR_PROMPT

    @property
    def patterns(self) -> dict[str, str]:
        return dict(PATTERNS)

    @property
    def definitions(self) -> list[AgentDefinition]:
        return list(self._definitions.values())

    def select(self, agents: Sequence[str] | None) -> list[AgentDefinition]:
        if not agents:
            return self.definitions
        missing = [a for a in agents if a not in self._definitions]
        if missing:
            raise ValueError(f"unknown agent(s): {', '.join(missing)}. available: {', '.join(self._definitions)}")
        return [self._definitions[a] for a in agents]

    async def run(
        self,
        pattern: str,
        task_text: str,
        *,
        agents: Sequence[str] | None = None,
        promote: bool = False,
        parent_scope: MemoryScope | None = None,
    ) -> AgentResult:
        """한 번의 오케스트레이션. 쉼표로 이은 패턴은 파이프라인(앞 결과가 뒤 입력).

        끝나면 부모 범위에 기록을 남기고 작업 공유 메모리를 비운다. promote 면 블랙보드 결과를
        shared 사실로 올린다.
        """
        stages = [p.strip().lower() for p in pattern.split(",") if p.strip()]
        unknown = [s for s in stages if s not in PATTERNS]
        if not stages or unknown:
            raise ValueError(f"unknown pattern(s): {', '.join(unknown) or pattern!r}. available: {', '.join(PATTERNS)}")
        definitions = self.select(agents)
        if not definitions:
            raise ValueError("no agents defined. add YAML definitions under agents_dir first")

        parent = parent_scope or current_scope.get() or MemoryScope(user_id=LOCAL_USER)
        task = AgentTask.create(task_text, context={"pattern": pattern}, scope=parent)
        orchestrators = [await self._build(stage, definitions, parent, task) for stage in stages]
        orchestrator: OrchestratorProtocol = (
            orchestrators[0] if len(orchestrators) == 1 else OrchestratorPipeline(orchestrators)
        )

        token = current_task.set(task.task_id)
        try:
            result = await orchestrator.dispatch(task)
            if promote:
                for stage in orchestrators:
                    await stage.promote([], scope=parent)
        finally:
            current_task.reset(token)
            if self._memory is not None:
                await self._memory.clear_task(task.task_id, parent)
        await self._record(pattern, task, result, parent)
        return result

    async def _build(
        self, stage: str, definitions: list[AgentDefinition], parent: MemoryScope, task: AgentTask
    ) -> BaseOrchestrator:
        nodes = [LazyAgentNode(d, self._factory, self._memory) for d in definitions]
        if stage == "hierarchical":
            topo = HierarchicalTopology()
            for definition, node in zip(definitions, nodes, strict=True):
                topo.add_node(node, level=definition.level)
            return HierarchicalOrchestrator(topo, memory=self._memory)
        if stage == "blackboard":
            btopo = BlackboardTopology()
            for node in nodes:
                btopo.add_node(node)
            return BlackboardOrchestrator(btopo, SharedBlackboard(), memory=self._memory)
        if stage == "market":
            mtopo = SupervisorTopology()
            for node in nodes:
                mtopo.add_node(node)
            return MarketOrchestrator(mtopo, memory=self._memory)
        # supervisor: 감독자 세션을 부모 범위의 자식으로 만들고, 참여 에이전트 도구를 꽂는다
        supervisor = AgentDefinition(
            name="supervisor",
            description="오케스트레이션 감독자",
            system_prompt=self._supervisor_prompt,
            tools=[f"agent_{d.name}" for d in definitions],
        )
        sup_node, _ = await self._factory.node_for(supervisor, parent, task)
        stopo = SupervisorTopology()
        for node in nodes:
            stopo.add_node(node)
        return SupervisorOrchestrator(stopo, sup_node._session, memory=self._memory)

    async def _record(self, pattern: str, task: AgentTask, result: AgentResult, parent: MemoryScope) -> None:
        if self._memory is None:
            return
        outcome = result.content if result.success else f"실패: {result.error}"
        try:
            await self._memory.remember(
                f"오케스트레이션({pattern}): '{_clip(task.content, 120)}' → {_clip(outcome, 300)}",
                source=ORCHESTRATION_SOURCE,
                scope=parent,
                tags=["orchestration", f"pattern:{pattern}"],
                metadata={"pattern": pattern, "task_id": task.task_id, "success": result.success},
            )
        except Exception:
            return


def load_supervisor_prompt(value: str) -> str | None:
    """설정값이 파일 경로면 내용을, 아니면 그 문자열을. 비면 None(기본 문구)."""
    from pathlib import Path

    text = (value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip() or None
    return text
