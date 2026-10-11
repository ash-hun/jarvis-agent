"""[memory] 요약이 덮지 않은 꼬리를 창 크기로 자르되 tool_use/tool_result 짝은 가르지 않는 컨텍스트 창."""

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


def summary_message(summary: str) -> UserMessage:
    return UserMessage(content=f"{SUMMARY_HEADER}\n{summary}")


def chars_of(messages: list[Message], summary: str | None = None) -> int:
    return sum(len(m.model_dump_json()) for m in messages) + (len(summary) if summary else 0)
