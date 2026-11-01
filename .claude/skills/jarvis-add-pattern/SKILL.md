---
name: jarvis-add-pattern
description: "Jarvis multi-agent 오케스트레이션 패턴 신규 추가. Orchestrator + Topology 파일 생성, __init__.py 등록, 테스트 작성까지 전 과정 안내. Triggers on: 'agent pattern 추가', 'new orchestrator', '오케스트레이션 패턴 추가', 'add pattern', 'multi-agent pattern'."
user-invocable: true
argument-hint: "<pattern-name> [설명]"
---

# Jarvis Add Agent Pattern

`src/jarvis/core/multi_agent/` 에 새로운 오케스트레이션 패턴을 추가한다.

## 전제 지식

**3계층 구조** (이 중 Orchestrator만 필수):

```
Topology     노드 연결 방식 (선택: 기존 4개로 충분하면 생략)
Orchestrator 작업 분배 로직 (필수: dispatch() 1개 구현)
Pipeline     패턴 조합 (OrchestratorPipeline 에 바로 끼움)
```

**핵심 계약** (`multi_agent_protocol.py`). Protocol 이 아니라 상속하는 기반 클래스다:
```python
class OrchestratorProtocol:
    async def dispatch(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError(...)
```
- `AgentTask(frozen=True)`: `task.task_id` = sha256(json(content, context))[:16]. `task.scope` 는 위임한 부모의 메모리 범위
- `AgentResult(frozen=True)`: `success`, `content`, `error`, `agent_name`
- `BaseOrchestrator.__init__(topology, memory=None)` (`orchestrators/orchestrator_base.py`): `self.topology`, `self.memory` 를 둔다. 다음 에이전트에게 결과를 넘길 때는 `await self.share(task, text, author)` 로 작업 공유 메모리에 쓴다. `task.context` 에만 넣으면 하위 에이전트 프롬프트에 닿지 않는다

**기존 패턴 참조**:
| 패턴 | 파일 | 특징 |
|------|------|------|
| Supervisor | `orchestrators/supervisor.py` | LLM이 tool_call로 노드 선택 |
| Hierarchical | `orchestrators/hierarchical.py` | 레벨 순차 + 동일레벨 병렬 |
| Market | `orchestrators/market.py` | `can_handle()` 입찰 → `score()` 가 가장 큰 노드 낙찰 |
| Blackboard | `orchestrators/blackboard.py` | 공유 상태 스냅샷 주입 |
| Pipeline | `orchestrators/pipeline.py` | fail-fast 다단계 합성 |

## 패턴 추가 절차

### 명세 수집

argument로 일부 제공됐으면 그걸 활용하고, 부족한 부분만 확인한다:

- **패턴 이름** (snake_case): 파일명, 클래스명, `PATTERNS` 키에 쓴다
- **분배 로직**: 어떤 기준으로 어떤 노드에게 task를 줄 것인가
- **Topology 필요 여부**: 노드 연결 방식이 기존 4개와 다른가
- **내부 상태**: `dispatch()` 호출 간 유지할 상태가 있는가 (예: RoundRobin의 `_index`)

### Topology 생성 (선택)

기존 `SupervisorTopology`(flat), `HierarchicalTopology`(레벨), `P2PTopology`(라우팅 테이블),
`BlackboardTopology`(공유 상태) 중 맞는 게 없을 때만 생성.

`src/jarvis/core/multi_agent/topologies/<name>.py`:
```python
from .topology_base import BaseTopology

class <Name>Topology(BaseTopology):
    # 추가 상태/메서드만 작성. add_node() 멱등성은 기반 클래스가 보장.
    pass
```

`topologies/__init__.py` 에 import 와 `__all__` 을 추가.

### Orchestrator 생성 (필수)

`src/jarvis/core/multi_agent/orchestrators/<name>.py`:
```python
from typing import Any

from jarvis.core.multi_agent.multi_agent_protocol import TopologyProtocol
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from .orchestrator_base import BaseOrchestrator

class <Name>Orchestrator(BaseOrchestrator):
    def __init__(self, topology: TopologyProtocol, memory: Any = None) -> None:
        super().__init__(topology, memory)
        # 내부 상태 초기화

    async def dispatch(self, task: AgentTask) -> AgentResult:
        nodes = self.topology.get_nodes()
        if not nodes:
            return AgentResult(
                task_id=task.task_id, agent_name="<name>_orchestrator",
                content="", success=False, error="No nodes in topology"
            )
        # 분배 로직 구현
        ...
```

**dispatch() 작성 규칙**:
- 빈 topology → `success=False, error="No nodes"` 반환 (예외 금지)
- 노드 실패 처리: `result.success` 체크 후 error 전파 여부 결정
- 하위 작업은 `AgentTask.create(..., parent_task_id=task.task_id, scope=task.scope)` 로 만든다. scope 를 빼면 자식 세션이 부모의 사용자를 잃는다
- `asyncio.gather()` 로 병렬 실행 가능 (동일 레벨 노드들)

### `__init__.py` 2곳 등록

**`orchestrators/__init__.py`**:
```python
from .<name> import <Name>Orchestrator  # 추가
__all__ = [..., "<Name>Orchestrator"]
```

**`multi_agent/__init__.py`**:
```python
from .orchestrators import <Name>Orchestrator  # 추가
__all__ = [..., "<Name>Orchestrator"]
```

### `/orchestrate` 와 `orchestrate` 도구에 연결

여기까지는 라이브러리로만 쓸 수 있다. 사용자와 메인 LLM 이 고르게 하려면:

- `multi_agent_service.py` 의 `PATTERNS` 에 `"<name>": "<언제 쓰는지 한 줄>"` 을 더한다. `orchestrate` 도구의 `pattern` enum 과 설명, `/orchestrate list` 가 이 사전에서 나온다
- 같은 파일 `OrchestrationService._build` 에 `if stage == "<name>":` 분기를 더해 `LazyAgentNode` 목록으로 토폴로지와 오케스트레이터를 만든다(`memory=self._memory` 를 넘긴다)
- `core/slash/orchestrate_cmd.py` 의 `_USAGE` 에 있는 pattern 목록에 이름을 더한다

### 테스트 작성 (필수)

`tests/unit/test_multi_agent_<name>.py` 를 만든다(예: `test_multi_agent_market.py`). 파일 첫 줄 docstring 은 `"""multi_agent: <무엇을 검증하는지>."""` 한 줄이다.

**반드시 포함해야 할 테스트 케이스**:
```python
class Test<Name>Orchestrator:

    @pytest.mark.asyncio
    async def test_기본_동작(self):
        """패턴의 핵심 분배 로직이 의도대로 작동하는지."""
        ...

    @pytest.mark.asyncio
    async def test_empty_topology_returns_failure(self):
        """빈 topology에서 success=False 반환."""
        topo = SupervisorTopology()  # 또는 해당 topology
        result = await <Name>Orchestrator(topo).dispatch(AgentTask.create("task"))
        assert not result.success

    @pytest.mark.asyncio
    async def test_node_failure_handling(self):
        """노드 실패 시 orchestrator가 어떻게 처리하는지."""
        ...

    # 패턴에 따라 추가:
    # - 병렬 실행이면: asyncio.sleep으로 elapsed time 검증
    # - 상태 유지이면: 연속 dispatch 간 상태 변이 검증
    # - 입찰이면: score/can_handle 조합 검증
```

`PATTERNS` 와 `_build` 에 연결했다면 `tests/unit/test_multi_agent_multi_agent_service.py` 에 새 이름으로 `run()` 이 도는 경우를 하나 더한다.

### 테스트 실행 및 검증

```bash
uv run pytest tests/unit -k multi_agent -v --tb=short
```

**전체 회귀 확인**:
```bash
uv run pytest --tb=short -q
uv run mypy
```

모든 테스트가 PASS여야 완료.

### 문서 갱신

- `website/docs/concepts/multi-agent-orchestration/orchestration-pattern.md` 의 패턴 표와 mermaid 에 새 패턴을 더한다
- `docs/features.md` 의 오케스트레이션 항목(구현 파일, 테스트 표)을 갱신한다

### 완료 안내

성공 시 사용자에게:

```
패턴 추가 완료: <Name>Orchestrator

  파일:
    src/jarvis/core/multi_agent/orchestrators/<name>.py
    [src/jarvis/core/multi_agent/topologies/<name>.py]  (topology 생성한 경우)

  등록:
    orchestrators/__init__.py
    multi_agent/__init__.py
    [multi_agent_service.py PATTERNS, _build]  (/orchestrate 에 연결한 경우)

  사용 예:
    from jarvis.core.multi_agent import <Name>Orchestrator, SupervisorTopology

    topo = SupervisorTopology()
    topo.add_node(my_agent_node)
    result = await <Name>Orchestrator(topo).dispatch(AgentTask.create("task"))

  Pipeline 조합:
    pipeline = OrchestratorPipeline([
        HierarchicalOrchestrator(plan_topo),
        <Name>Orchestrator(exec_topo),
    ])
```

## 멱등성 체크리스트

새 패턴이 이 규칙을 지키는지 확인:

- [ ] `add_node()` 중복 호출 시 두 번째는 무시되는가 (기반 클래스가 보장하므로 별도 구현 불필요)
- [ ] 동일 `task_id` 재호출 시 같은 결과를 내는가 (캐시 or 결정론적 로직)
- [ ] 빈 topology에서 예외 대신 `AgentResult(success=False)` 반환하는가
- [ ] `dispatch()`가 외부 shared state를 직접 변경하지 않는가 (Blackboard 예외)
