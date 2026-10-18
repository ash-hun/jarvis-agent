"""[memory] 사용자가 알려 준 작업 방식(언제, 어떻게)을 에이전트 전용 절차 기억으로 바꾸고 질의에 맞추는 순수 함수."""

import re
import hashlib
from dataclasses import dataclass, field

from jarvis.memory.scope import MemoryScope
from jarvis.memory.types import MemoryItem

TASK_PATTERN_SOURCE = "task_pattern"
PATTERN_HEADER = "[작업 패턴]"  # 사용자가 알려 준 방식. 같은 종류의 요청이면 이대로 한다
SAVE_HINT_HEADER = "[작업 패턴 저장]"
SAVE_HINT = (
    "사용자가 작업을 어떻게 할지 설명하거나 앞으로 이렇게 하라고 했다면, 답하기 전에 remember_task_pattern 으로"
    " 이름, 언제(어떤 요청일 때), 어떻게(단계와 기본값), 키워드를 저장한다. 말로만 기억하겠다고 하지 않는다."
)
# 사용자가 방식을 가르치는 말. 걸리면 저장하라는 안내를 붙인다(저장 판단은 모델이 한다)
TEACHING_RE = re.compile(
    r"기억해|기억하고|기억해\s*둬|앞으로|다음부터|다음에도|이런\s*요청|비슷한\s*요청|이렇게\s*(?:해|하면|계산)|이\s*방식|항상"
)
MAX_KEYWORDS = 8


@dataclass(frozen=True)
class TaskPattern:
    name: str  # 짧은 이름. 같은 이름으로 다시 저장하면 덮어쓴다
    when: str  # 어떤 요청일 때
    steps: str  # 어떻게. 단계와 기본값
    keywords: tuple[str, ...] = field(default_factory=tuple)  # 요청에 이 말이 들어 있으면 떠올린다

    def content(self) -> str:
        return f"{self.name}\n언제: {self.when}\n어떻게: {self.steps}\n키워드: {', '.join(self.keywords)}"

    def metadata(self) -> dict[str, object]:
        return {"name": self.name, "when": self.when, "steps": self.steps, "keywords": list(self.keywords)}


def normalize_keywords(raw: object) -> tuple[str, ...]:
    """쉼표 문자열이나 목록을 소문자, 중복 없는 키워드로. 한 글자는 거의 모든 요청에 걸려 뺀다."""
    items = raw.split(",") if isinstance(raw, str) else list(raw) if isinstance(raw, list | tuple) else []
    seen: list[str] = []
    for item in items:
        word = str(item).strip().lower()
        if len(word) >= 2 and word not in seen:
            seen.append(word)
    return tuple(seen[:MAX_KEYWORDS])


def pattern_id(scope: MemoryScope, name: str) -> str:
    """자연 키: (사용자, 에이전트, 이름). 같은 패턴을 다시 저장하면 같은 항목을 덮는다."""
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    key = f"{scope.user_id}|{scope.agent_id}|{normalized}"
    return "tp_" + hashlib.sha1(key.encode()).hexdigest()[:29]


def from_item(item: MemoryItem) -> TaskPattern | None:
    meta = item.metadata
    if item.source != TASK_PATTERN_SOURCE or not meta.get("name"):
        return None
    return TaskPattern(
        str(meta["name"]), str(meta.get("when", "")), str(meta.get("steps", "")),
        normalize_keywords(meta.get("keywords", [])),
    )


def score(pattern: TaskPattern, query: str) -> int:
    """요청 글에 든 키워드 수. 한국어 조사가 붙어도 걸리게 부분 문자열로 본다."""
    text = query.lower()
    return sum(1 for word in pattern.keywords if word in text)


def best_matches(patterns: list[TaskPattern], query: str, limit: int) -> list[TaskPattern]:
    scored = [(score(p, query), p) for p in patterns]
    return [p for s, p in sorted(scored, key=lambda sp: -sp[0]) if s > 0][:limit]


def teaches(query: str) -> bool:
    return bool(TEACHING_RE.search(query))


def render_block(patterns: list[TaskPattern]) -> str:
    body = "\n".join(f"- {p.name}\n  언제: {p.when}\n  어떻게: {p.steps}" for p in patterns)
    return f"{PATTERN_HEADER} 사용자가 알려 준 방식이다. 이번 요청이 해당하면 되묻지 말고 이대로 한다.\n{body}"
