"""[memory] 세션 종료 때 세션 전체 대화를 요약해 그 세션 범위의 private 일화로 남긴다."""

from typing import TYPE_CHECKING

from jarvis.model_layer.types import LLMContext, Message, ModelConfig, StreamOptions, UserMessage
from jarvis.memory.consolidation.compaction import system_prompt_for
from jarvis.memory.scope import MemoryScope

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService


class EpisodicSummarizer:
    def __init__(self, model: ModelConfig, memory: "MemoryService") -> None:
        self._model = model
        self._memory = memory

    async def save_session(
        self,
        session_id: str,
        messages: list[Message],
        scope: MemoryScope | None = None,
    ) -> str | None:
        """저장된 항목 id. 메시지가 없거나 요약 LLM 호출이 실패하면 None."""
        if not messages:
            return None
        summary = await self._summarize(session_id, messages)
        if summary is None:
            return None
        resolved = self._memory.resolve_scope(scope).with_session(session_id)
        return await self._memory.remember(summary, source="session_end", scope=resolved)

    async def _summarize(self, session_id: str, messages: list[Message]) -> str | None:
        from jarvis.model_layer.stream import stream_to_message

        parts: list[str] = []
        for m in messages:
            if hasattr(m, "text") and callable(m.text):
                content = m.text() or "[no text]"
            elif isinstance(m.content, str):
                content = m.content
            else:
                content = m.model_dump_json()
            parts.append(f"[{m.role}] {content}")

        ctx = LLMContext(
            messages=[
                UserMessage(
                    content=(
                        f"다음은 세션 '{session_id}'의 대화 내용입니다.\n"
                        "핵심 결정, 학습 내용, 중요 사실을 요약하라:\n\n" + "\n".join(parts)
                    )
                )
            ],
            system_prompt=system_prompt_for(messages),
        )
        result = await stream_to_message(self._model, ctx, StreamOptions())
        if result.error_message is not None:
            return None
        return result.text().strip() or "[summary unavailable]"
