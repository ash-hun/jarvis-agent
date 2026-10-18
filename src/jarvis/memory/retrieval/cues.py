"""[memory] 저장 때 남긴 단서(범위, 태그)와 질의 단서가 겹칠수록 잘 떠오르게 하는 부호화 특수성 점수."""

from jarvis.memory.stores.protocol import tokens_of
from jarvis.memory.scope import MemoryScope
from jarvis.memory.types import MemoryItem


def cue_overlap(item: MemoryItem, scope: MemoryScope, query: str) -> float:
    """0..1. 범위 일치(같은 세션 > 같은 에이전트)와 태그 겹침의 평균."""
    if item.scope.session_id and item.scope.session_id == scope.session_id:
        context = 1.0
    elif item.scope.agent_id == scope.agent_id:
        context = 0.5
    else:
        context = 0.0
    tag_tokens = {t.lower() for tag in item.tags for t in tag.replace(":", " ").split() if t}
    query_tokens = set(tokens_of(query))
    tags = len(tag_tokens & query_tokens) / len(query_tokens) if tag_tokens and query_tokens else 0.0
    return (context + tags) / 2
