"""[agent_layer] LLM 호출 하나의 입력을 시스템, 사고, 도구, 메시지 블록별 글자 수로 나눠 잰다."""

import json

from jarvis.model_layer.model_types import LLMContext, Message, UserMessage


def measure_prompt(context: LLMContext, thought_block: str = "") -> dict[str, int]:
    """부분별 글자 수를 프롬프트에 놓이는 순서대로 돌려준다. 같은 이름의 메시지 블록은 합친다.

    system 은 사고 블록을 뺀 기본 지시문이다. 메모리가 붙인 블록은 첫 줄의 `[머리말]` 로, 나머지는 role 로 묶는다.
    """
    system = context.system_prompt or ""
    if thought_block and system.endswith(thought_block):
        system = system[: -len(thought_block)].rstrip()
    sizes: dict[str, int] = {
        "system": len(system),
        "inner_thought": len(thought_block),
        "tools": sum(len(json.dumps(t.model_dump(), ensure_ascii=False)) for t in context.tools or []),
    }
    for message in context.messages:
        label = _label(message)
        sizes[label] = sizes.get(label, 0) + _chars(message)
    return sizes


def _label(message: Message) -> str:
    if isinstance(message, UserMessage) and isinstance(message.content, str):
        head = message.content.lstrip().split("\n", 1)[0]
        if head.startswith("[") and "]" in head:
            return head[: head.index("]") + 1]
    return message.role


def _chars(message: Message) -> int:
    content = message.content
    if isinstance(content, str):
        return len(content)
    return len(json.dumps([c.model_dump() for c in content], ensure_ascii=False))
