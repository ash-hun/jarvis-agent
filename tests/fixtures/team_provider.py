"""JARVIS 와 KAREN 이 서로 묻고 답하는 대화를 각본대로 흉내 내는 테스트용 프로바이더."""

import json
import asyncio
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


def _text(message: UserMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else "".join(getattr(c, "text", "") for c in content)


class TeamProvider:
    """시스템 프롬프트에 '카렌'이 있으면 KAREN, 없으면 JARVIS 로 행동한다.

    - JARVIS 가 "카렌에게" 를 받으면 ask_agent(karen) 를 부른다
    - KAREN 이 JARVIS 의 요청을 받으면 사용자 관심 분야를 ask_agent(main) 로 되묻는다
    - JARVIS 가 KAREN 의 요청을 받으면 바로 답한다
    - 도구 결과를 받으면 그 결과를 정리해 답한다
    step_delay 만큼 쉬어 두 에이전트가 동시에 일하는 구간을 만든다
    """

    provider_name = "team"

    def __init__(self, step_delay: float = 0.05) -> None:
        self.step_delay = step_delay
        self.calls: list[tuple[str, str]] = []

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        await asyncio.sleep(self.step_delay)
        karen = KAREN_MARK in (context.system_prompt or "")
        who = "karen" if karen else "main"
        last = context.messages[-1]
        if isinstance(last, ToolResultMessage):
            result = "".join(getattr(c, "text", "") for c in last.content)
            self.calls.append((who, "summarize"))
            yield TextDeltaEvent(delta=f"정리: {result}")
            yield StopEvent(reason="stop", usage=Usage(input=1, output=1))
            return
        text = _text(last) if isinstance(last, UserMessage) else ""
        if not karen and "카렌에게" in text:
            self.calls.append((who, "ask karen"))
            yield _tool_call("main-ask", "karen", "AI 뉴스 3개를 찾아 줘")
        elif karen and text.startswith("[J.A.R.V.I.S."):
            self.calls.append((who, "ask main back"))
            yield _tool_call("karen-ask", "main", "사용자가 관심 있는 분야가 뭐야?")
        elif not karen and text.startswith("[K.A.R.E.N."):
            self.calls.append((who, "answer karen"))
            yield TextDeltaEvent(delta="AI 반도체")
            yield StopEvent(reason="stop", usage=Usage(input=1, output=1))
            return
        else:
            self.calls.append((who, "plain"))
            yield TextDeltaEvent(delta="네")
            yield StopEvent(reason="stop", usage=Usage(input=1, output=1))
            return
        yield StopEvent(reason="tool_use", usage=Usage(input=1, output=1))


def _tool_call(call_id: str, agent: str, message: str) -> ToolCallDeltaEvent:
    return ToolCallDeltaEvent(
        id=call_id, name="ask_agent", arguments_delta=json.dumps({"agent": agent, "message": message})
    )
