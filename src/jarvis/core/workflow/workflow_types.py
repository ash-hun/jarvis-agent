"""[core] Workflow 화면이 받는 위임 간선과 백그라운드 작업 기록 값 타입."""

from typing import Any, Literal
from dataclasses import asdict, dataclass

DelegationKind = Literal["ask", "subagent", "orchestrate", "focus"]
JobKind = Literal["schedule", "proactive", "consolidate", "external"]


@dataclass(frozen=True)
class DelegationEdge:
    """source 에이전트가 target 에게 일을 맡긴 한 번. 끝나지 않았으면 ended_ms 와 ok 가 None 이다."""

    edge_id: str
    kind: DelegationKind
    source: str
    target: str
    label: str
    started_ms: int
    ended_ms: int | None = None
    ok: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobRecord:
    """백그라운드 작업 하나의 마지막 실행. running 이면 지금 도는 중이다."""

    job_id: str
    kind: JobKind
    label: str
    runs: int
    running: bool
    last_started_ms: int | None = None
    last_ended_ms: int | None = None
    last_ok: bool | None = None
    last_error: str = ""
    fail_streak: int = 0  # 마지막 성공 뒤 연속 실패 수. 성공하면 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
