"""[memory] 세기, 순서, 시간을 묻는 질문에 대상별 일화를 시간순으로 늘어놓은 블록을 짓는 순수 규칙."""

import re
from collections.abc import Sequence

from jarvis.memory.memory_types import TURN_INDEX, TURN_PART, MemoryItem

TIMELINE_HEADER = "[대상 타임라인]"
# 대상 하나에 늘어놓는 줄 수와 줄마다 남기는 글자 수. 집계형 질문에만 붙어 약 4,000자가 상한이다
TIMELINE_MAX_LINES = 40
SNIPPET_CHARS = 100

# 회상 3개로는 풀 수 없는 질문(모든 발생을 세거나 줄 세워야 하는 것). 모델 대신 코드가 가려 호출을 늘리지 않는다
_AGGREGATE = re.compile(
    r"how (many|long|often)|in (what|which) order|chronolog|\border\b|\bfirst\b|\blast\b|most recent|"
    r"\b(second|third|nth)\b|\bsince\b|\bago\b|\bbefore\b|\bafter\b|\btimes\b|\bwhen did\b|"
    r"몇\s*(번|개|명|회|달|일|주|년)|얼마나 (오래|자주)|순서|처음|마지막|최근|언제|전에|후에|이후|이전",
    re.IGNORECASE,
)


def is_aggregate(question: str) -> bool:
    """세기, 순서, 기간, n번째를 묻는 질문인가. 순수 함수."""
    return bool(_AGGREGATE.search(question))


def mentions(name: str, items: Sequence[MemoryItem]) -> list[MemoryItem]:
    """이름이 글자로 나오는 항목만 시간순으로. 같은 날이면 세션 안 턴 번호와 조각 번호 순. 순수 함수.

    벡터로만 비슷한 항목은 넣지 않는다. 세는 질문에서 비슷한 다른 대상이 섞이면 개수가 틀린다.
    """
    # ponytail: 별칭을 합치지 않는다("엄마"와 "어머니"는 다른 대상),
    # 같은 대상이 이름 여럿으로 갈려 세는 일이 보이면 엔티티 사전을 둔다
    key = name.lower()
    hits = [item for item in items if key in item.content.lower()]
    return sorted(hits, key=_order)


def render_timeline(name: str, items: Sequence[MemoryItem], max_lines: int = TIMELINE_MAX_LINES) -> str:
    """'[대상 타임라인] 이름: 언급 n건, 오래된 것부터' 와 날짜 붙은 줄. 넘치면 최근 것만 남기고 그렇다고 적는다."""
    if not items:
        return ""
    shown = list(items)[-max_lines:]
    head = f"{TIMELINE_HEADER} {name}: 언급 {len(items)}건, 오래된 것부터"
    if len(shown) < len(items):
        head += f"(최근 {len(shown)}건만)"
    lines = [f"- [{_date(item)}] {snippet(item.content, name)}" for item in shown]
    return "\n".join([head, *lines])


def snippet(text: str, name: str, width: int = SNIPPET_CHARS) -> str:
    """이름이 처음 나온 자리를 가운데 둔 한 줄. 줄바꿈은 공백으로."""
    flat = " ".join(text.split())
    at = max(0, flat.lower().find(name.lower()))
    start = max(0, at - width // 2)
    piece = flat[start : start + width]
    return ("…" if start > 0 else "") + piece + ("…" if start + width < len(flat) else "")


def _order(item: MemoryItem) -> tuple[float, int, int]:
    when = item.occurred_at or item.created_at
    return when.timestamp(), int(item.metadata.get(TURN_INDEX, 0) or 0), int(item.metadata.get(TURN_PART, 0) or 0)


def _date(item: MemoryItem) -> str:
    return (item.occurred_at or item.created_at).strftime("%Y-%m-%d")
