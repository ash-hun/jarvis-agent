"""[core] 같은 (content, context) 가 항상 같은 task_id 를 갖는 불변 AgentTask 와 그 결과 AgentResult 를 정한다."""

import json
import hashlib
from typing import Any
from datetime import UTC, datetime
from dataclasses import dataclass, field

from jarvis.memory.scope import MemoryScope


def _make_task_id(content: str, context: dict[str, Any]) -> str:
    payload = json.dumps(
        {"content": content, "context": context},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class AgentTask:
    """frozen dataclass. 동일 (content, context) 조합은 항상 동일 task_id 라 재시도/중복 실행에 안전하다."""

    task_id: str
    content: str
    context: dict[str, Any]
    parent_task_id: str | None
    created_at: datetime
    scope: MemoryScope | None = None  # 위임한 쪽(부모)의 메모리 범위. 자식 범위는 여기서 파생한다

    @classmethod
    def create(
        cls,
        content: str,
        context: dict[str, Any] | None = None,
        parent_task_id: str | None = None,
        scope: MemoryScope | None = None,
    ) -> "AgentTask":
        ctx = context or {}
        return cls(
            task_id=_make_task_id(content, ctx),
            content=content,
            context=ctx,
            parent_task_id=parent_task_id,
            created_at=datetime.now(UTC),
            scope=scope,
        )


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    agent_name: str
    content: str
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
