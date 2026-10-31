"""memory 기능의 일화 기억 정책: 사건 시각은 처음 한 번만 정하고 다시 불러도 덮지 않는다."""

from datetime import datetime

from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.memory.long_term.episodic import prepare_episode
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def test_prepare_episode_sets_occurred_at_once():
    item = MemoryItem(content="회의", kind=MemoryKind.EPISODIC, scope=SCOPE, created_at=datetime(2024, 1, 2))

    assert prepare_episode(item).occurred_at == datetime(2024, 1, 2)
    item.occurred_at = datetime(2023, 12, 31)
    assert prepare_episode(item).occurred_at == datetime(2023, 12, 31)
