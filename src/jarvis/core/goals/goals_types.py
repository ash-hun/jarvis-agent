"""[core] 목표 한 건의 모델과 자연 키, 에이전트 답 해석, 새로 알릴 항목 고르기, 진행 기록 갱신 같은 순수 규칙."""

import re
import hashlib
from typing import Any, Literal
from pydantic import BaseModel, Field
from dataclasses import dataclass, replace

from jarvis.agent_layer.openloop.openloop_types import normalize_description
from jarvis.core.scheduler.task import GOAL_PREFIX

GoalStatus = Literal["active", "done", "paused"]
# 진행 기록은 다음 차례 프롬프트에 들어간다. 길어지면 비용만 늘어 최근 것만 둔다
MAX_NOTES = 20
# 알린 항목의 키. 같은 것을 두 번 알리지 않으려고 둔다. 오래된 것부터 버린다
MAX_REPORTED = 200
# 매일 9~21시 매시 정각. 사람이 깨어 있을 때만 진행하고 알린다
DEFAULT_SCHEDULE = "0 9-21 * * *"
TASK_PREFIX = GOAL_PREFIX
# 사용자에게 허락이나 값을 구하는 항목의 키 머리. 프롬프트가 이 머리를 쓰라고 시킨다
ASK_PREFIX = "ask-"
# 에이전트 답의 줄 머리. 이 꼴로 답하라고 프롬프트가 시킨다
_FIELD = re.compile(r"^\s*(머리|항목|기록|완료)\s*[:：]\s*(.*)$")
# 항목: [키] 한 줄. 키가 없는 항목은 무엇을 알리는지 몰라 버린다
_ITEM = re.compile(r"^\[([^\]]+)\]\s*(.+)$")
# 도구 결과 안의 '항목: [키] 줄'. 도구가 지은 줄은 모델을 거치지 않고 그대로 알린다
_TOOL_ITEM = re.compile(r"항목\s*[:：]\s*\[([^\]]+)\]\s*(.+)$")
_DONE_WORDS = ("예", "네", "yes", "true", "완료")
_BLANKS = ("", "없음", "비움", "none")


class Goal(BaseModel):
    """목표 한 건. id 는 (에이전트, 목표 문장)에서 나온 자연 키라 같은 목표를 두 번 맡겨도 하나다."""

    id: str
    agent: str
    text: str
    status: GoalStatus = "active"
    schedule: str = DEFAULT_SCHEDULE
    notes: list[str] = Field(default_factory=list)
    reported: list[str] = Field(default_factory=list)
    runs: int = 0
    # 지난 차례에 모델이 부른 도구(name, params)와 그 결과 글의 지문. 다시 불러 같으면 모델을 건너뛴다
    last_calls: list[dict[str, Any]] = Field(default_factory=list)
    seen: str = ""
    created_at: int = 0
    updated_at: int = 0

    @property
    def task_name(self) -> str:
        return TASK_PREFIX + self.id


@dataclass(frozen=True)
class Step:
    """한 차례에 대한 에이전트의 답. items 는 지금 기준으로 알릴 만한 것 전부(이미 알린 것 포함)다."""

    head: str = ""
    items: tuple[tuple[str, str], ...] = ()
    note: str = ""
    done: bool = False
    parsed: bool = False  # 약속한 꼴로 답했는가. 평가 지표다
    keyless: int = 0  # 키 없이 와서 버린 항목 수. 평가 지표다


def goal_key(agent: str, text: str) -> str:
    """자연 키: 에이전트와 공백, 대소문자를 정리한 목표 문장. 생성 시각이나 자동 증가 값은 쓰지 않는다."""
    raw = f"{agent}|{normalize_description(text)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _blank(text: str) -> str:
    """'없음', '-', '(비움)' 같은 빈 표시는 빈 글로."""
    return "" if text.strip("()[]-. ").lower() in _BLANKS else text.strip()


def parse_step(reply: str) -> Step:
    """'머리: / 항목: [키] 줄 / 기록: / 완료:' 꼴의 답을 읽는다.

    모델이 머리표를 빼고 '[키] 줄' 만 쓰거나 첫 줄에 머리 문장만 쓸 때가 있다(실측). 그 꼴도 받는다.
    """
    head: list[str] = []
    items: list[tuple[str, str]] = []
    note, done, parsed, keyless = "", False, False, 0
    current = ""

    def item(value: str) -> None:
        nonlocal keyless
        if not _blank(value):
            return
        m = _ITEM.match(value)
        if m is None or not _blank(m.group(1)):
            keyless += 1
            return
        items.append((m.group(1).strip(), m.group(2).strip()))

    for raw in reply.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _FIELD.match(line)
        if m is None:
            if _ITEM.match(line):
                parsed = True
                item(line)
            elif current in ("", "머리") and not items:
                head.append(line)
            continue
        current, value = m.group(1), m.group(2).strip()
        parsed = True
        if current == "머리":
            head = [value]
        elif current == "항목":
            item(value)
        elif current == "기록":
            note = _blank(value)
        else:
            done = value.lower().startswith(_DONE_WORDS)
    if not parsed:
        return Step()
    return Step(_blank("\n".join(head)), tuple(items), note, done, parsed, keyless)


def new_items(goal: Goal, step: Step) -> list[tuple[str, str]]:
    """아직 알리지 않은 항목. 같은 키가 한 답에 두 번 와도 하나다. 순수 함수."""
    seen = set(goal.reported)
    fresh = []
    for key, line in step.items:
        if key not in seen:
            seen.add(key)
            fresh.append((key, line))
    return fresh


def compose(step: Step, items: list[tuple[str, str]]) -> str:
    """사용자에게 건넬 말: 머리 한 문장과 새 항목 줄. 새 항목이 없으면 빈 글."""
    if not items:
        return ""
    lines = [line for _, line in items]
    # 머리가 항목 말을 그대로 되풀이하거나(묻는 항목 하나일 때 잦다), 묻기만 하는데 추천 머리를 붙이면 뺀다
    asking = all(key.startswith(ASK_PREFIX) for key, _ in items)
    head = step.head if step.head and not asking and not any(line in step.head for line in lines) else ""
    return "\n".join([head, *lines] if head else lines)


def with_tool_items(step: Step, results: list[str]) -> Step:
    """도구가 지은 항목 줄을 답의 항목에 더한다. 같은 키면 도구 줄이 이긴다. 순수 함수.

    모델에게 옮기게 하면 키를 빼고 말만 쓰거나 링크를 줄여, 알릴 것이 있어도 알리지 못했다(실측).
    """
    found = [
        (m.group(1).strip(), m.group(2).strip())
        for text in results for line in text.splitlines() if (m := _TOOL_ITEM.search(line))
    ]
    if not found:
        return step
    keys = {key for key, _ in found}
    return replace(step, items=(*found, *(item for item in step.items if item[0] not in keys)))


def worth_noting(step: Step, used_tool: bool) -> bool:
    """이 차례의 기록을 남길지. 도구 없이 답한 차례는 새로 안 것이 없고, 묻기만 한 차례의 기록("현금을 몰라")은
    사용자가 답한 뒤에도 남아 다음 차례가 그 기록대로 다시 묻게 했다(실측). 순수 함수."""
    asked_only = bool(step.items) and all(k.startswith(ASK_PREFIX) for k, _ in step.items)
    return used_tool and not asked_only


def fingerprint(results: list[str]) -> str:
    """도구 결과 글들의 지문. 같은 글이면 같은 값이다. 순수 함수."""
    return hashlib.sha1("\x00".join(results).encode()).hexdigest()


def advance(goal: Goal, step: Step, delivered: list[str], now_ms: int) -> Goal:
    """한 차례의 결과를 목표에 적는다. 같은 키를 두 번 적어도 한 번만 남는다. 순수 함수."""
    notes = [*goal.notes, step.note][-MAX_NOTES:] if step.note else goal.notes
    return mark_reported(goal, delivered, now_ms).model_copy(update={
        "notes": notes,
        "status": "done" if step.done else goal.status,
        "runs": goal.runs + 1,
    })


def mark_reported(goal: Goal, keys: list[str], now_ms: int) -> Goal:
    """사용자에게 건넨 항목의 키를 적는다. 같은 키를 두 번 적어도 한 번만 남는다. 순수 함수."""
    reported = [*goal.reported, *(k for k in keys if k not in goal.reported)][-MAX_REPORTED:]
    return goal.model_copy(update={"reported": reported, "updated_at": now_ms})
