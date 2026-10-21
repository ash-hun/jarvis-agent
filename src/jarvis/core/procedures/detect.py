"""[core] 세션 이력에서 "도구를 여러 번 써서 성공으로 끝난 작업 구간"을 찾는 순수 함수."""

from typing import Any
from dataclasses import dataclass

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
    """사용자 메시지부터 다음 사용자 메시지 전까지가 한 구간.

    실패한 도구 호출은 뒤에서 같은 도구가 성공했으면 회복으로 보고 절차에서 뺀다.
    회복하지 못한 오류가 있으면 구간을 버린다.
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
    calls: list[tuple[str, ToolStep]] = []  # (호출 id, 단계)
    failed: set[str] = set()
    outcome = ""
    for m in messages[start + 1 : end]:
        if isinstance(m, AssistantMessage):
            if m.error_message:
                return None
            calls.extend((tc.id, ToolStep(name=tc.name, args=dict(tc.arguments))) for tc in m.tool_calls())
            if m.stop_reason == "stop" and m.text().strip():
                outcome = m.text().strip()
        elif isinstance(m, ToolResultMessage) and m.is_error:
            failed.add(m.tool_call_id)
    if not request or not outcome or not _recovered(calls, failed):
        return None
    steps = tuple(step for call_id, step in calls if call_id not in failed)
    return TaskSpan(start=start, request=request, steps=steps, outcome=outcome)


def _recovered(calls: list[tuple[str, ToolStep]], failed: set[str]) -> bool:
    """실패한 호출마다 그 뒤에 같은 도구의 성공한 호출이 있다."""
    for i, (call_id, step) in enumerate(calls):
        if call_id in failed and not any(
            later_id not in failed and later.name == step.name for later_id, later in calls[i + 1 :]
        ):
            return False
    return True
