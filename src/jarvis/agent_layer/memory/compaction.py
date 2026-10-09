from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jarvis.memory.scope import scope_from_context
from jarvis.model_layer.types import Message, ModelConfig, UserMessage

if TYPE_CHECKING:
    from jarvis.memory.manager import MemoryManager


class CompactionMiddleware:
    """
    컨텍스트 토큰이 임계값을 초과하면 오래된 메시지를 LLM으로 요약.
    memory 가 설정된 경우 요약 결과를 실행 에이전트의 private 일화로 저장 (source="auto_summary").
    Pi: AgentHarness.compact() 동일 패턴.
    """

    def __init__(
        self,
        model: ModelConfig,
        threshold_chars: int = 80_000,
        keep_recent: int = 10,
        memory: MemoryManager | None = None,
    ) -> None:
        self._model = model
        self._threshold_chars = threshold_chars
        self._keep_recent = keep_recent
        self._memory = memory

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]:
        total_chars = sum(len(m.model_dump_json()) for m in messages)
        if total_chars <= self._threshold_chars:
            return messages

        to_compact = messages[: -self._keep_recent]
        keep = messages[-self._keep_recent:]

        if not to_compact:
            return messages

        summary = await self._summarize(to_compact)
        if summary is None:
            # 요약 실패 — 이번 턴은 압축을 건너뛴다. 빈 요약으로 히스토리를 대체하면 맥락이 사라진다.
            return messages

        if self._memory is not None:
            await self._memory.remember(summary, source="auto_summary", scope=scope_from_context(context))

        summary_msg = UserMessage(
            content=f"[Compacted context summary]\n{summary}"
        )
        return [summary_msg] + keep

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        pass

    async def retrieve(self, query: str, context: dict[str, Any], limit: int = 10) -> list[Message]:
        return []

    async def clear(self, context: dict[str, Any]) -> None:
        pass

    async def _summarize(self, messages: list[Message]) -> str | None:
        from jarvis.model_layer.stream import stream_to_message
        from jarvis.model_layer.types import LLMContext, StreamOptions

        text = "\n".join(
            f"[{m.role}] " + (m.content if isinstance(m.content, str) else m.model_dump_json())
            for m in messages
        )
        ctx = LLMContext(
            messages=[UserMessage(content=f"Summarize the following conversation concisely:\n\n{text}")],
            system_prompt=(
                "You are a summarization assistant. "
                "Produce a dense summary preserving key facts, decisions, and context."
            ),
        )
        result = await stream_to_message(self._model, ctx, StreamOptions())
        if result.error_message is not None:
            return None
        return result.text() or "[summary unavailable]"
