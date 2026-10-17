"""[core] Focus 작업 상태와 진행률, 예상 시간, 명령 해석을 계산하는 순수 함수."""

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

AREAS = ("reference", "log", "analysis", "progress")
STOP_WORDS = frozenset({"stop", "off", "end", "종료", "끝", "그만"})
ANALYSIS_KEYS = ("purpose", "reuse", "needs", "next", "prepare")
ANALYSIS_TITLES = {
    "purpose": "근본 목적",
    "reuse": "이전 지시에서 쓸 것",
    "needs": "필요한 것",
    "next": "예상 다음 지시",
    "prepare": "미리 대비할 것",
}
_COMMAND = re.compile(r"^\s*/focus(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class FocusStep:
    title: str
    done_at: float | None = None

    @property
    def done(self) -> bool:
        return self.done_at is not None


@dataclass(frozen=True)
class FocusState:
    task_id: str
    session_id: str
    task: str
    started_at: float
    steps: tuple[FocusStep, ...] = ()
    instructions: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "task": self.task,
            "started_at": self.started_at,
            "steps": [{"title": s.title, "done_at": s.done_at} for s in self.steps],
            "instructions": list(self.instructions),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FocusState":
        return cls(
            task_id=data["task_id"],
            session_id=data["session_id"],
            task=data["task"],
            started_at=float(data["started_at"]),
            steps=tuple(FocusStep(s["title"], s.get("done_at")) for s in data.get("steps", [])),
            instructions=tuple(data.get("instructions", [])),
        )


@dataclass(frozen=True)
class FocusCommand:
    action: Literal["start", "stop", "status"]
    task: str = ""


def parse_command(text: str) -> FocusCommand | None:
    """'/focus <작업>' 은 시작, '/focus stop' 은 종료, '/focus' 만 있으면 현황. 다른 문장은 None."""
    m = _COMMAND.match(text)
    if m is None:
        return None
    arg = (m.group(1) or "").strip()
    if not arg:
        return FocusCommand("status")
    if arg.lower() in STOP_WORDS:
        return FocusCommand("stop")
    return FocusCommand("start", arg)


def progress(steps: tuple[FocusStep, ...]) -> float:
    """완료한 단계 / 전체 단계. 단계가 없으면 0."""
    if not steps:
        return 0.0
    return sum(s.done for s in steps) / len(steps)


def eta_sec(state: FocusState, now: float) -> float | None:
    """지금까지 걸린 시간 / 완료한 단계 수 × 남은 단계 수. 완료한 단계가 없으면 추정하지 않는다.

    완료가 늦어지면 단계당 시간이 늘어 예상도 같이 늘어난다(멈춘 작업이 0분으로 보이지 않게)."""
    done = sum(s.done for s in state.steps)
    remaining = len(state.steps) - done
    if not done:
        return None
    return (max(now - state.started_at, 0.0) / done) * remaining


def apply_plan(steps: tuple[FocusStep, ...], plan: list[dict[str, Any]], now: float) -> tuple[FocusStep, ...]:
    """tracker 가 준 단계 목록으로 바꾼다. 이미 끝난 단계는 완료 시각을 지키고, 새로 끝난 단계에만 now 를 찍는다."""
    done_at = {s.title: s.done_at for s in steps if s.done_at is not None}
    merged: list[FocusStep] = []
    seen: set[str] = set()
    for item in plan:
        title = str(item.get("title", "")).strip()
        if not title or title in seen:
            continue
        seen.add(title)
        if title in done_at:
            merged.append(FocusStep(title, done_at[title]))
        else:
            merged.append(FocusStep(title, now if item.get("done") else None))
    return tuple(merged) if merged else steps


def with_instruction(state: FocusState, text: str) -> FocusState:
    return replace(state, instructions=(*state.instructions, text))


def extract_json(raw: str) -> dict[str, Any] | None:
    """코드펜스나 잡텍스트에 둘러싸인 JSON 객체를 관대하게 꺼낸다."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def render_analysis(analysis: dict[str, Any]) -> str:
    """분석 5항목을 패널 마크다운으로. 항목 아래 내용은 한 단계 들여 쓰고, 비어 있으면 '없음'.

    analyze 가 남긴 instruction, at 이 있으면 어느 지시의 분석인지 맨 위에 적는다.
    """
    lines: list[str] = []
    if analysis.get("instruction"):
        at = f" · {analysis['at']}" if analysis.get("at") else ""
        lines.append(f"*지시: {analysis['instruction']}{at}*")
    for key in ANALYSIS_KEYS:
        value = analysis.get(key)
        items = value if isinstance(value, list) else [value] if value else []
        lines.append(f"- **{ANALYSIS_TITLES[key]}**")
        lines += [f"  - {item}" for item in items] or ["  - 없음"]
    return "\n".join(lines)


def latest_section(text: str, marker: str) -> str:
    """marker 로 시작하는 마지막 절부터 끝까지. marker 가 없으면 전체."""
    at = text.rfind(marker)
    return text[at:] if at >= 0 else text


def state_payload(state: FocusState, now: float) -> dict[str, Any]:
    """focus_state 이벤트 본문. 매번 전체를 보내 화면이 받은 것으로 덮어쓰게 한다."""
    return {
        "active": True,
        "task_id": state.task_id,
        "task": state.task,
        "steps": [{"title": s.title, "done": s.done} for s in state.steps],
        "progress": progress(state.steps),
        "eta_sec": eta_sec(state, now),
        "elapsed_sec": max(now - state.started_at, 0.0),
    }
