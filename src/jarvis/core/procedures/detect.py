"""[core] 세션 이력에서 "도구를 여러 번 써서 성공으로 끝난 작업 구간"을 찾는 순수 함수."""

from dataclasses import dataclass
from typing import Any

from jarvis.model_layer.types import AssistantMessage, Message, ToolResultMessage

DEFAULT_MIN_TOOL_CALLS = 3


@dataclass(frozen=True)
class ToolStep:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class TaskSpan:
    start: int  # 이력 안 사용자 메시지 인덱스. 세션 id 와 합쳐 절차의 자연 키가 된다
    request: str
    steps: tuple[ToolStep, ...]
    outcome: str

    @property
    def tool_names(self) -> tuple[str, ...]:
        seen: list[str] = []
        for step in self.steps:
            if step.name not in seen:
                seen.append(step.name)
        return tuple(seen)


def find_spans(messages: list[Message], min_tool_calls: int = DEFAULT_MIN_TOOL_CALLS) -> list[TaskSpan]:
    """사용자 메시지부터 다음 사용자 메시지 전까지가 한 구간. 도구 오류가 하나라도 있으면 버린다.

    # ponytail: 중간에 실패했다가 회복한 작업도 통째로 버린다, 회복 패턴 자체를 배우고 싶어지면 오류 뒤 성공을 허용
    """
    starts = [i for i, m in enumerate(messages) if m.role == "user" and isinstance(m.content, str)]
    spans: list[TaskSpan] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(messages)
        span = _span(messages, start, end)
        if span is not None and len(span.steps) >= min_tool_calls:
            spans.append(span)
    return spans


def _span(messages: list[Message], start: int, end: int) -> TaskSpan | None:
    request = str(messages[start].content).strip()
    steps: list[ToolStep] = []
    outcome = ""
    for m in messages[start + 1 : end]:
        if isinstance(m, AssistantMessage):
            if m.error_message:
                return None
            steps.extend(ToolStep(name=tc.name, args=dict(tc.arguments)) for tc in m.tool_calls())
            if m.stop_reason == "stop" and m.text().strip():
                outcome = m.text().strip()
        elif isinstance(m, ToolResultMessage) and m.is_error:
            return None
    if not request or not outcome:
        return None
    return TaskSpan(start=start, request=request, steps=tuple(steps), outcome=outcome)
