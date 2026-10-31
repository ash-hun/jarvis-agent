"""[memory] 이력을 메시지 수나 턴 수로 자르되 tool_use/tool_result 짝은 가르지 않는 컨텍스트 창."""

from jarvis.model_layer.types import Message, UserMessage

SUMMARY_HEADER = "[Compacted context summary]"


def cut_at_user_boundary(messages: list[Message]) -> list[Message]:
    """첫 user 메시지부터 돌려준다. 앞에 tool_result 나 assistant 가 고아로 남으면 provider 가 거부한다."""
    for i, m in enumerate(messages):
        if m.role == "user":
            return messages[i:]
    return messages


def apply_window(messages: list[Message], window_size: int) -> list[Message]:
    if window_size <= 0 or len(messages) <= window_size:
        return messages
    return cut_at_user_boundary(messages[-window_size:])


def turn_starts(messages: list[Message]) -> list[int]:
    """턴은 user 메시지 하나와 그 뒤의 답, 도구 호출, 도구 결과다. 각 턴이 시작하는 위치."""
    return [i for i, m in enumerate(messages) if m.role == "user"]


def last_turns(messages: list[Message], turns: int) -> list[Message]:
    starts = turn_starts(messages)
    if turns <= 0 or len(starts) <= turns:
        return cut_at_user_boundary(messages)
    return messages[starts[-turns]:]


def summary_message(summary: str) -> UserMessage:
    return UserMessage(content=f"{SUMMARY_HEADER}\n{summary}")


def chars_of(messages: list[Message], summary: str | None = None) -> int:
    return sum(len(m.model_dump_json()) for m in messages) + (len(summary) if summary else 0)
