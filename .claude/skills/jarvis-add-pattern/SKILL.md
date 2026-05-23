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
Topology    — 노드 연결 방식 (선택: 기존 4개로 충분하면 생략)
Orchestrator — 작업 분배 로직 (필수: dispatch() 1개 구현)
Pipeline    — 패턴 조합 (OrchestratorPipeline에 바로 끼움)
```

**핵심 계약** (`protocol.py`):
```python
class OrchestratorProtocol(Protocol):
    async def dispatch(self, task: AgentTask) -> AgentResult: ...
```
- `AgentTask(frozen=True)` — `task.task_id` = sha256(content+context)[:16]
- `AgentResult(frozen=True)` — `success`, `content`, `error`, `agent_name`
- `BaseOrchestrator.__init__(topology)` — `self.topology` 자동 설정

**기존 패턴 참조**:
| 패턴 | 파일 | 특징 |
|------|------|------|
| Supervisor | `orchestrators/supervisor.py` | LLM이 tool_call로 노드 선택 |
| Hierarchical | `orchestrators/hierarchical.py` | 레벨 순차 + 동일레벨 병렬 |
| Market | `orchestrators/market.py` | `can_handle()` 입찰 → priority 낙찰 |
| Blackboard | `orchestrators/blackboard.py` | 공유 상태 스냅샷 주입 |
| Pipeline | `orchestrators/pipeline.py` | fail-fast 다단계 합성 |

## 패턴 추가 절차

### Step 1 — 명세 수집

argument로 일부 제공됐으면 그걸 활용하고, 부족한 부분만 확인한다:

1. **패턴 이름** (snake_case): 파일명 및 클래스명에 사용
2. **분배 로직**: 어떤 기준으로 어떤 노드에게 task를 줄 것인가
3. **Topology 필요 여부**: 노드 연결 방식이 기존 4개와 다른가
4. **내부 상태**: `dispatch()` 호출 간 유지할 상태가 있는가 (예: RoundRobin의 `_index`)

### Step 2 — Topology 생성 (선택)

기존 `SupervisorTopology`(flat), `HierarchicalTopology`(트리), `P2PTopology`(라우팅 테이블),
`BlackboardTopology`(공유 상태) 중 맞는 게 없을 때만 생성.

`src/jarvis/core/multi_agent/topologies/<name>.py`:
```python
from .base import BaseTopology

class <Name>Topology(BaseTopology):
    # 추가 상태/메서드만 작성. add_node() 멱등성은 Base가 보장.
    pass
```

`topologies/__init__.py`에 import 추가.

### Step 3 — Orchestrator 생성 (필수)

`src/jarvis/core/multi_agent/orchestrators/<name>.py`:
```python
from jarvis.core.multi_agent.task import AgentTask, AgentResult
from .base import BaseOrchestrator

class <Name>Orchestrator(BaseOrchestrator):
    def __init__(self, topology) -> None:
        super().__init__(topology)
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
- `AgentTask.create(..., parent_task_id=task.task_id)` 로 계층 추적
- `asyncio.gather()` 로 병렬 실행 가능 (동일 레벨 노드들)

### Step 4 — `__init__.py` 2곳 등록

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

### Step 5 — 테스트 작성 (필수)

`tests/unit/test_multi_agent/test_orchestrators.py` 에 클래스 추가:

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
    # - 입찰이면: priority/can_handle 조합 검증
```

### Step 6 — 테스트 실행 및 검증

```bash
uv run pytest tests/unit/test_multi_agent/ -v --tb=short
```

**전체 회귀 확인**:
```bash
uv run pytest --tb=short -q
```

모든 테스트가 PASS여야 완료.

### Step 7 — 완료 안내

성공 시 사용자에게:

```
✓ 패턴 추가 완료: <Name>Orchestrator

  파일:
    src/jarvis/core/multi_agent/orchestrators/<name>.py
    [src/jarvis/core/multi_agent/topologies/<name>.py]  (topology 생성한 경우)

  등록:
    orchestrators/__init__.py
    multi_agent/__init__.py

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

- [ ] `add_node()` 중복 호출 시 두 번째는 무시되는가 (Base가 보장하므로 별도 구현 불필요)
- [ ] 동일 `task_id` 재호출 시 같은 결과를 내는가 (캐시 or 결정론적 로직)
- [ ] 빈 topology에서 예외 대신 `AgentResult(success=False)` 반환하는가
- [ ] `dispatch()`가 외부 shared state를 직접 변경하지 않는가 (Blackboard 예외)
