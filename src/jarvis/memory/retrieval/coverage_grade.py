"""[memory] 회상 항목이 질문의 대상을 덮는지 가리고, 빠진 대상의 항목을 같은 개수 안에 섞는 순수 규칙."""

from collections.abc import Sequence

from jarvis.memory.memory_types import MemoryItem
from jarvis.model_layer.embeddings import cosine

# 대상 이름과 항목 벡터가 이 이상 비슷하면 글자가 달라도 덮은 것으로 본다(bge-m3 기준)
COVER_SIMILARITY = 0.6


def uncovered(
    names: Sequence[str],
    items: Sequence[MemoryItem],
    name_vectors: Sequence[list[float] | None] = (),
    threshold: float = COVER_SIMILARITY,
) -> list[str]:
    """어떤 항목에도 글자로 나오지 않고 벡터로도 가깝지 않은 대상. 순서는 names 를 따른다."""
    texts = [item.content.lower() for item in items]
    vectors = [item.embedding for item in items if item.embedding]
    out: list[str] = []
    for i, name in enumerate(names):
        if any(name.lower() in text for text in texts):
            continue
        vector = name_vectors[i] if i < len(name_vectors) else None
        if vector and any(cosine(vector, v) >= threshold for v in vectors):
            continue
        out.append(name)
    return out


def merge_coverage(first: Sequence[MemoryItem], extra: Sequence[MemoryItem], limit: int) -> list[MemoryItem]:
    """1차 회상의 뒷순위를 추가 항목으로 바꿔 limit 개를 넘기지 않는다. 1차 1순위는 늘 남긴다.

    노출 개수를 늘리면 다른 항목이 밀리거나 모델이 덜 맞는 것을 붙잡는다(출처 발췌 실험에서 손해였다).
    """
    seen = {item.id for item in first}
    fresh: list[MemoryItem] = []
    for item in extra:
        if item.id not in seen:
            seen.add(item.id)
            fresh.append(item)
    keep = max(1, limit - len(fresh)) if first else 0
    return [*first[:keep], *fresh][:limit]
