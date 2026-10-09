from __future__ import annotations

from typing import TYPE_CHECKING

from jarvis.model_layer.types import Message, ModelConfig, UserMessage

if TYPE_CHECKING:
    from jarvis.agent_layer.memory.backends.protocol import LTMBackend


class EpisodicSummarizer:
    """
    세션 종료 시 전체 대화를 LLM으로 요약해 LTM에 영구 저장.

    저장 시 source="session_end" — LongTermMemory.transform()이 다음 세션에서 자동 주입.
    """

    def __init__(self, model: ModelConfig, ltm_backend: LTMBackend) -> None:
        self._model = model
        self._ltm_backend = ltm_backend

    async def save_session(
        self,
        session_id: str,
        messages: list[Message],
    ) -> str | None:
        """
        세션 메시지를 요약해 LTM에 저장.

        Returns:
            저장된 entry_id. 메시지가 없거나 요약 LLM 호출이 실패하면 None.
        """
        if not messages:
            return None

        summary = await self._summarize(session_id, messages)
        if summary is None:
            return None

        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        entry = MemoryEntry(
            content=summary,
            source="session_end",
            session_id=session_id,
        )
        return await self._ltm_backend.store(entry)

    async def _summarize(self, session_id: str, messages: list[Message]) -> str | None:
        from jarvis.model_layer.stream import stream_to_message
        from jarvis.model_layer.types import LLMContext, StreamOptions

        text_parts: list[str] = []
        for m in messages:
            if hasattr(m, "text") and callable(m.text):
                content = m.text() or "[no text]"
            elif isinstance(m.content, str):
                content = m.content
            else:
                content = m.model_dump_json()
            text_parts.append(f"[{m.role}] {content}")

        conversation_text = "\n".join(text_parts)
        ctx = LLMContext(
            messages=[
                UserMessage(
                    content=(
                        f"다음은 세션 '{session_id}'의 대화 내용입니다.\n"
                        "핵심 결정, 학습 내용, 중요 사실을 간결하게 요약해주세요 (한국어):\n\n"
                        f"{conversation_text}"
                    )
                )
            ],
            system_prompt=(
                "You are a summarization assistant. "
                "Produce a dense summary preserving key decisions, facts, and context."
            ),
        )
        result = await stream_to_message(self._model, ctx, StreamOptions())
        if result.error_message is not None:
            return None
        return result.text() or "[summary unavailable]"
