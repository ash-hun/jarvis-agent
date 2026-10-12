"""사용자가 알려 준 작업 방식을 KAREN 이 저장하고 다음 세션에서 그대로 쓰는 흐름을 흉내 내는 테스트용 프로바이더."""

import asyncio
import json
from collections.abc import AsyncIterator

from jarvis.model_layer.types import (
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    ToolCallDeltaEvent,
    ToolResultMessage,
    Usage,
    UserMessage,
)

KAREN_MARK = "카렌"
PATTERN_ARGS = {
    "name": "예산 기반 공고 추천",
    "when": "총예산과 보유 현금으로 공고를 추천해 달라는 요청",
    "steps": "대출 = 공고 금액 - 현금. 금리 연 4%, 30년 가정. housing_budget 으로 바로 찾는다",
    "keywords": "예산, 현금, 추천",
}
BUDGET_ARGS = {"budget": 300_000_000, "cash": 120_000_000, "monthly_limit": 2_000_000}
ASK_BACK = "대출 금액과 금리를 알려 주세요."


def _text(message: object) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else "".join(getattr(c, "text", "") for c in content)


class PatternProvider:
    """컨텍스트에 붙은 메모리 블록을 보고 움직인다. 실제 모델이 블록을 읽고 따르는 것을 각본으로 둔다.

    - [작업 패턴 저장] 안내가 있으면 remember_task_pattern 을 부른다
    - [작업 패턴] 블록이 있으면 되묻지 않고 housing_budget 을 부른다
    - 둘 다 없으면 예전처럼 되묻는다
    """

    provider_name = "pattern"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.saw_pattern: list[tuple[str, bool]] = []

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        await asyncio.sleep(0.01)
        who = "karen" if KAREN_MARK in (context.system_prompt or "") else "main"
        last = context.messages[-1]
        blocks = [_text(m) for m in context.messages if isinstance(m, UserMessage)]
        if isinstance(last, ToolResultMessage):
            self.calls.append((who, "say"))
            yield TextDeltaEvent(delta=f"{who} 정리: {_text(last)}")
            yield StopEvent(reason="stop", usage=Usage(input=1, output=1))
            return
        pattern = any(b.startswith("[작업 패턴]") for b in blocks)
        self.saw_pattern.append((who, pattern))
        if any(b.startswith("[작업 패턴 저장]") for b in blocks):
            tool, args = "remember_task_pattern", PATTERN_ARGS
        elif pattern:
            tool, args = "housing_budget", BUDGET_ARGS
        else:
            self.calls.append((who, "ask back"))
            yield TextDeltaEvent(delta=ASK_BACK)
            yield StopEvent(reason="stop", usage=Usage(input=1, output=1))
            return
        self.calls.append((who, tool))
        yield ToolCallDeltaEvent(id=f"{who}-{len(self.calls)}", name=tool, arguments_delta=json.dumps(args))
        yield StopEvent(reason="tool_use", usage=Usage(input=1, output=1))
