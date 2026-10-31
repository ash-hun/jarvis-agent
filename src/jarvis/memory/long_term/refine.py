"""[memory] 같은 작업 종류의 성공한 턴 일화가 쌓이면 절차(PDM)로 정제할 후보를 고르는 순수 함수."""

from datetime import datetime
from dataclasses import dataclass
from collections.abc import Iterable

from jarvis.memory.stores.store_protocol import OUTCOME, TASK_TYPE
from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.memory.scope import MemoryScope

MIN_SUCCESSES = 3  # 한 번 성공은 우연일 수 있다. 같은 종류가 이만큼 성공해야 절차로 본다
CHAT_TASK = "chat"  # 도구를 부르지 않은 턴. 따라 할 절차가 없다
SUCCESS = "success"


@dataclass(frozen=True)
class Candidate:
    agent_id: str
    task_type: str
    evidence: tuple[MemoryItem, ...]  # 오래된 것부터

    @property
    def generation(self) -> int:
        """성공이 MIN_SUCCESSES 개 쌓일 때마다 한 세대. 같은 세대는 다시 정제하지 않는다."""
        return len(self.evidence) // MIN_SUCCESSES

    @property
    def source(self) -> str:
        """절차 저장소의 자연 키. 같은 에이전트, 종류, 세대면 같은 값이다."""
        return f"edm:{self.agent_id}:{self.task_type}:{self.generation}"


def candidates(episodes: Iterable[MemoryItem], scope: MemoryScope) -> list[Candidate]:
    """scope 의 에이전트가 직접 겪은 성공 일화만 센다. 다른 에이전트의 일화는 읽을 수 있어도 섞지 않는다."""
    groups: dict[str, list[MemoryItem]] = {}
    for item in episodes:
        task = item.metadata.get(TASK_TYPE)
        if (
            item.kind is MemoryKind.EPISODIC
            and item.scope.user_id == scope.user_id
            and item.scope.agent_id == scope.agent_id
            and task and task != CHAT_TASK
            and item.metadata.get(OUTCOME) == SUCCESS
        ):
            groups.setdefault(str(task), []).append(item)
    return [
        Candidate(scope.agent_id, task, tuple(sorted(items, key=_at)))
        for task, items in sorted(groups.items())
        if len(items) >= MIN_SUCCESSES
    ]


def _at(item: MemoryItem) -> tuple[datetime, str]:
    return (item.occurred_at or item.created_at, item.id)
