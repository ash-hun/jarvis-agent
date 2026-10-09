"""의미 기억 정책. "주제: 값" 형태의 사실은 같은 주제의 옛 사실을 대체한다(삭제가 아니라 superseded_by)."""

from jarvis.memory.stores.protocol import ItemStore
from jarvis.memory.types import MemoryItem, MemoryKind

KEY_TAG = "key:"
MAX_KEY_CHARS = 40


def fact_key(content: str) -> str | None:
    """'거주지: 서울' 의 '거주지'. 콜론이 없거나 주제가 너무 길면 사실 형태가 아니라고 본다."""
    head, sep, _ = content.partition(":")
    key = head.strip().lower()
    if not sep or not key or len(key) > MAX_KEY_CHARS or "\n" in key:
        return None
    return key


def prepare_fact(item: MemoryItem) -> MemoryItem:
    """의미 항목의 주제를 태그로 남겨 검색 단서와 충돌 탐지에 쓴다. 유효 시작 시각은 생성 시각."""
    key = fact_key(item.content)
    if key is not None and f"{KEY_TAG}{key}" not in item.tags:
        item.tags.append(f"{KEY_TAG}{key}")
    if item.valid_from is None:
        item.valid_from = item.created_at
    return item


async def supersede_conflicts(store: ItemStore, item: MemoryItem) -> list[str]:
    """같은 소유자(user, agent) 안에서 같은 주제의 더 오래된 의미 항목을 이 항목으로 대체한다. 대체한 id 목록."""
    key = fact_key(item.content)
    if key is None:
        return []
    tag = f"{KEY_TAG}{key}"
    candidates = await store.recent(item.scope, kinds=[MemoryKind.SEMANTIC], limit=200)
    replaced: list[str] = []
    for other in candidates:
        if other.id == item.id or tag not in other.tags:
            continue
        if other.scope.user_id != item.scope.user_id or other.scope.agent_id != item.scope.agent_id:
            continue
        if other.created_at > item.created_at:
            # 더 새로운 사실이 이미 있다(과거 시점의 사실을 뒤늦게 적는 경우). 새 항목 쪽이 대체된다
            await store.supersede(item.id, other.id)
            return replaced
        await store.supersede(other.id, item.id)
        replaced.append(other.id)
    return replaced
