"""[scripts] 같은 작업을 패턴마다 고정 시간 자는 가짜 서브 에이전트에게 맡겨 벽시계 시간과 호출 수를 잰다."""

import os
import sys
import json
import time
import asyncio
import argparse
import statistics
from typing import Any
from pathlib import Path
from collections.abc import AsyncIterator

os.environ.setdefault("JARVIS_LLM__PROVIDER", "faux")
os.environ.setdefault("JARVIS_LOG_LEVEL", "WARNING")

from jarvis.model_layer.model_types import (
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    ToolCallDeltaEvent,
    ToolResultMessage,
    Usage,
)
from jarvis.core.multi_agent.orchestrators.hierarchical import HierarchicalOrchestrator
from jarvis.core.multi_agent.orchestrators.orchestrator_base import BaseOrchestrator
from jarvis.core.multi_agent.orchestrators.blackboard import BlackboardOrchestrator
from jarvis.core.multi_agent.orchestrators.supervisor import SupervisorOrchestrator
from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.core.multi_agent.orchestrators.pipeline import OrchestratorPipeline
from jarvis.core.multi_agent.topologies.blackboard import BlackboardTopology
from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology
from jarvis.core.multi_agent.orchestrators.market import MarketOrchestrator
from jarvis.core.multi_agent.multi_agent_protocol import AgentNodeProtocol
from jarvis.model_layer.model_registry import get_default_registry
from jarvis.core.policy.authenticator import NoAuthAuthenticator
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from jarvis.core.policy.validator import DefaultInputValidator
from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.multi_agent.node import capability_score
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.core.policy.pipeline import SecurityPipeline
from jarvis.core.policy.sandbox import PermissiveSandbox
from jarvis.memory.memory_service import MemoryService
from jarvis.core.policy.policy import AllowAllPolicy
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.session import AgentSession
from jarvis.memory.scope import MemoryScope
import jarvis

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "orchestration_patterns"
SUB_SEC = 0.2  # 서브 에이전트 한 번(모델 호출 포함)을 대신하는 고정 시간
MODEL_SEC = 0.2  # 감독자 LLM 호출 한 번을 대신하는 고정 시간
REPEATS = 5
TASK = "분기 보고서 작성: 시장 조사 후 정리하고 검토"
# (이름, level, capabilities). 계획 → 조사와 작성 → 검토
AGENTS = [
    ("planner", 0, ["계획"]),
    ("researcher", 1, ["조사"]),
    ("writer", 1, ["작성", "정리"]),
    ("reviewer", 2, ["검토"]),
]
PROVIDER = "supervisor_script"


class FakeAgent(AgentNodeProtocol):
    """SUB_SEC 만 자고 이름이 붙은 정해진 답을 낸다. 받은 앞 결과 수를 남긴다."""

    def __init__(self, name: str, capabilities: list[str], calls: list[tuple[str, int]]) -> None:
        self.name = name
        self.capabilities = capabilities
        self._calls = calls

    def score(self, task: AgentTask) -> float:
        return capability_score(task, self.name, self.capabilities)

    async def can_handle(self, task: AgentTask) -> bool:
        return self.score(task) > 0

    async def invoke(self, task: AgentTask) -> AgentResult:
        upstream = len(task.context.get("previous_results", [])) + sum(
            1 for k in task.context.get("blackboard", {}) if str(k).startswith("result_")
        ) + (1 if task.context.get("previous_result") else 0)
        self._calls.append((self.name, upstream))
        await asyncio.sleep(SUB_SEC)
        return AgentResult(task_id=task.task_id, agent_name=self.name, content=f"{self.name} 결과", success=True)


class SupervisorScript:
    """감독자 LLM 대역. fanout 이면 한 번에 네 에이전트를 부르고, serial 이면 한 차례에 하나씩 부른다."""

    provider_name = PROVIDER

    def __init__(self) -> None:
        self.mode = "fanout"
        self.calls = 0

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        await asyncio.sleep(MODEL_SEC)
        done = sum(isinstance(m, ToolResultMessage) for m in context.messages)
        pending = [name for name, _, _ in AGENTS][done:]
        if not pending:
            yield TextDeltaEvent(delta="최종 정리")
            yield StopEvent(reason="stop", usage=Usage(input=1, output=1))
            return
        for name in pending if self.mode == "fanout" else pending[:1]:
            yield ToolCallDeltaEvent(id=f"c-{name}", name=f"agent_{name}", arguments_delta=json.dumps({"task": TASK}))
        yield StopEvent(reason="tool_use", usage=Usage(input=1, output=1))


def _supervisor_session(root: str) -> AgentSession:
    repo = JsonlSessionRepo(sessions_root=root)
    return AgentSession(
        model=ModelConfig(provider=PROVIDER, model="script"),
        session_id="supervisor",
        security_pipeline=SecurityPipeline(
            validator=DefaultInputValidator(), authenticator=NoAuthAuthenticator(),
            policy=AllowAllPolicy(), sandbox=PermissiveSandbox(),
        ),
        plugin_runner=PluginRunner(),
        memory=None,
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        session_repo=repo,
    )


async def _build(stage: str, calls: list[tuple[str, int]], memory: MemoryService, root: str) -> BaseOrchestrator:
    nodes = [(FakeAgent(name, caps, calls), level) for name, level, caps in AGENTS]
    if stage == "hierarchical":
        htopo = HierarchicalTopology()
        for node, level in nodes:
            htopo.add_node(node, level=level)
        return HierarchicalOrchestrator(htopo, memory=memory)
    if stage == "blackboard":
        from jarvis.core.multi_agent.blackboard import SharedBlackboard

        btopo = BlackboardTopology()
        for node, _ in nodes:
            btopo.add_node(node)
        return BlackboardOrchestrator(btopo, SharedBlackboard(), memory=memory)
    stopo = SupervisorTopology()
    for node, _ in nodes:
        stopo.add_node(node)
    if stage == "market":
        return MarketOrchestrator(stopo, memory=memory)
    session = _supervisor_session(root)
    await session._session_repo.create(session_id="supervisor")
    return SupervisorOrchestrator(stopo, session, memory=memory)


async def run_once(pattern: str, script: SupervisorScript, root: str) -> dict[str, Any]:
    calls: list[tuple[str, int]] = []
    memory = MemoryService(InMemoryItemStore())
    script.calls = 0
    script.mode = "serial" if pattern == "supervisor_serial" else "fanout"
    stages = ["supervisor" if p.startswith("supervisor") else p for p in pattern.split(",")]
    orchestrators = [await _build(s, calls, memory, f"{root}/{pattern}-{time.perf_counter_ns()}") for s in stages]
    orchestrator = orchestrators[0] if len(orchestrators) == 1 else OrchestratorPipeline(orchestrators)
    task = AgentTask.create(TASK, context={"pattern": pattern}, scope=MemoryScope(user_id="local"))
    start = time.perf_counter()
    result = await orchestrator.dispatch(task)
    took = time.perf_counter() - start
    return {
        "wall_s": took,
        "sub_agent_calls": len(calls),
        "model_calls": script.calls,
        "agents": sorted({n for n, _ in calls}),
        "saw_upstream": sum(1 for _, up in calls if up > 0),
        "success": result.success,
    }


async def measure() -> dict[str, Any]:
    import tempfile

    script = SupervisorScript()
    get_default_registry().register(script)
    patterns = ["supervisor", "supervisor_serial", "hierarchical", "market", "blackboard", "hierarchical,blackboard"]
    rows = []
    with tempfile.TemporaryDirectory() as root:
        for pattern in patterns:
            runs = [await run_once(pattern, script, root) for _ in range(REPEATS)]
            walls = [r["wall_s"] for r in runs]
            first = runs[0]
            rows.append({
                "pattern": pattern,
                "wall_s_mean": round(statistics.mean(walls), 3),
                "wall_s_min": round(min(walls), 3),
                "wall_s_max": round(max(walls), 3),
                "sub_agent_calls": first["sub_agent_calls"],
                "supervisor_model_calls": first["model_calls"],
                "agents_used": first["agents"],
                "calls_that_saw_upstream": first["saw_upstream"],
                "success": all(r["success"] for r in runs),
            })
    return {"rows": rows, "repeats": REPEATS, "sub_agent_s": SUB_SEC, "supervisor_model_s": MODEL_SEC, "task": TASK}


def write(result: dict[str, Any]) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data[KEY] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"jarvis from {jarvis.__file__}", file=sys.stderr)
    result = asyncio.run(measure())
    print(json.dumps(result, ensure_ascii=False))
    if not args.dry_run:
        write(result)


if __name__ == "__main__":
    main()
