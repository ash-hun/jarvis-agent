"""agent_loop 테스트가 같이 쓰는, 턴마다 다른 응답을 흘리는 프로바이더와 이벤트 묶음."""

import json
import itertools
from typing import Any
from collections.abc import AsyncIterator

from jarvis.model_layer.model_types import (
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    ToolCallDeltaEvent,
    Usage,
)
from jarvis.model_layer.model_registry import get_default_registry

_IDS = itertools.count()


class ScriptedProvider:
    """호출 순서대로 미리 정한 이벤트 목록을 흘린다. 마지막 목록은 이후 호출에도 반복된다."""

    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        # 레지스트리는 먼저 등록한 쪽이 이겨서 테스트마다 다른 이름으로 등록한다
        self.provider_name = f"scripted-{next(_IDS)}"
        self._turns = turns
        self.calls: list[LLMContext] = []

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append(context)
        for event in self._turns[min(len(self.calls) - 1, len(self._turns) - 1)]:
            yield event


def register(provider: Any) -> ModelConfig:
    get_default_registry().register(provider)
    return ModelConfig(provider=provider.provider_name, model="scripted-model")


def text_turn(text: str) -> list[StreamEvent]:
    return [TextDeltaEvent(delta=text), StopEvent(reason="stop", usage=Usage(input=3, output=4))]


def tool_turn(*calls: tuple[str, str, dict[str, Any]]) -> list[StreamEvent]:
    events: list[StreamEvent] = [
        ToolCallDeltaEvent(id=tc_id, name=name, arguments_delta=json.dumps(args)) for tc_id, name, args in calls
    ]
    events.append(StopEvent(reason="tool_use", usage=Usage()))
    return events
