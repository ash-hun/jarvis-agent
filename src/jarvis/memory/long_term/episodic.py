"""[memory] 일화 기억 정책으로 사건 시각을 붙인다(최근 것이 먼저 떠오르는 가중치는 retrieval.scoring)."""

from jarvis.memory.types import MemoryItem


def prepare_episode(item: MemoryItem) -> MemoryItem:
    if item.occurred_at is None:
        item.occurred_at = item.created_at
    return item
