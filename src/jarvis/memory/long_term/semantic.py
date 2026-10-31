"""[memory] 의미 기억 정책으로, "주제: 값" 사실은 같은 주제의 옛 사실을 대체하고 비슷한 쌍은 간섭 후보로 표시한다."""

from jarvis.memory.stores.store_protocol import ItemStore, tokens_of
from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.memory.scope import MemoryScope

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


# 주제가 다른 비슷한 쌍은 표시만 한다. 자동 대체는 오탐 시 사실을 잃는다
CONFLICTS_KEY = "conflicts_with"  # metadata 에 남기는 간섭 후보 id 목록
DEFAULT_INTERFERENCE_THRESHOLD = 0.6


def _body(content: str) -> str:
    """'주제: 값' 이면 값만. 주제가 다른데 값이 같은 쌍이 간섭이다."""
    return content.partition(":")[2].strip() if fact_key(content) is not None else content


def similarity(a: str, b: str) -> float:
    """값 부분의 토큰 자카드. 벡터가 생기면 코사인으로 바꿀 자리."""
    ta, tb = set(tokens_of(_body(a))), set(tokens_of(_body(b)))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_interference(
    items: list[MemoryItem], threshold: float = DEFAULT_INTERFERENCE_THRESHOLD
) -> list[tuple[str, str]]:
    """같은 주제 태그가 없는데(같은 주제면 대체 규칙이 처리) 내용이 threshold 이상 비슷한 의미 항목 쌍."""
    pairs: list[tuple[str, str]] = []
    for i, a in enumerate(items):
        key_a = fact_key(a.content)
        for b in items[i + 1 :]:
            if key_a is not None and key_a == fact_key(b.content):
                continue
            if similarity(a.content, b.content) >= threshold:
                pairs.append((a.id, b.id))
    return pairs


async def mark_interference(
    store: ItemStore, scope: MemoryScope, threshold: float = DEFAULT_INTERFERENCE_THRESHOLD
) -> int:
    """소유자의 의미 항목에서 간섭 쌍을 찾아 양쪽 metadata 에 표시한다. 이미 표시된 쌍은 건너뛴다(멱등)."""
    items = [
        i for i in await store.recent(scope, kinds=[MemoryKind.SEMANTIC], limit=200)
        if i.scope.user_id == scope.user_id and i.scope.agent_id == scope.agent_id
    ]
    by_id = {i.id: i for i in items}
    marked = 0
    for a_id, b_id in find_interference(items, threshold):
        for this_id, other_id in ((a_id, b_id), (b_id, a_id)):
            item = by_id[this_id]
            existing = list(item.metadata.get(CONFLICTS_KEY, []))
            if other_id in existing:
                continue
            item.metadata[CONFLICTS_KEY] = [*existing, other_id]
            await store.store(item)
            marked += 1
    return marked
