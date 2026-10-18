"""[core] 한 번 실행 작업을 등록할 때 LLM 으로 알림(reminder)과 작업(task)을 가른다."""

import asyncio
from typing import TYPE_CHECKING, Literal
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.model_layer.types import ModelConfig

Kind = Literal["reminder", "task"]
DEFAULT_TIMEOUT_SEC = 15.0

_PROMPT = """\
사용자가 정한 시각에 받을 항목을 분류한다.
- 그 시각에 문구를 그대로 알려주기만 하면 되면 REMINDER
- 그 시각에 에이전트가 무언가를 조사·작성·요약·실행해서 결과를 알려줘야 하면 TASK

예시:
물 마시기 → REMINDER
회의 준비 알림 → REMINDER
알림 하나줘 → REMINDER
엄마한테 전화하라고 알려줘 → REMINDER
오늘 뉴스 요약해줘 → TASK
경쟁사 가격 웹검색으로 정리해줘 → TASK

REMINDER 또는 TASK 한 단어로만 답하라.

항목: {text}"""


def make_llm_classifier(model: "ModelConfig", timeout: float = DEFAULT_TIMEOUT_SEC) -> Callable[[str], Awaitable[Kind]]:
    """등록 때 한 번 LLM 으로 알림/작업을 가르는 분류기. 실패·시간 초과·애매한 답은 reminder."""

    async def classify(text: str) -> Kind:
        from jarvis.model_layer.types import LLMContext, StreamOptions, UserMessage
        from jarvis.model_layer.stream import stream_to_message

        ctx = LLMContext(messages=[UserMessage(content=_PROMPT.format(text=text))], tools=None)
        try:
            msg = await asyncio.wait_for(stream_to_message(model, ctx, StreamOptions()), timeout)
        except Exception:
            return "reminder"
        return "task" if "TASK" in (msg.text() or "").upper() else "reminder"

    return classify
