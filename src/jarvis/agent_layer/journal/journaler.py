"""[agent_layer] LTM 의 최근 사고 로그를 LLM 으로 성찰해 저널 항목(source=journal)으로 남긴다."""

from typing import TYPE_CHECKING

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamOptions, UserMessage
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
from jarvis.model_layer.stream import stream_to_message

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService
    from jarvis.memory.scope import MemoryScope

# 저널 항목을 식별하는 LTM source 태그.
JOURNAL_SOURCE = "journal"

DEFAULT_PROMPT = """\
너는 Jarvis의 "자기 성찰 저널" 작성자다. 아래는 최근 너의 내적 사고(ThoughtFrame) 기록이다.
반복되는 패턴, 잘한 판단, 개선할 점을 메타 관찰로 1~3문장만 적어라. 사용자에게 말하는 게
아니라 스스로 돌아보는 기록이다. 관찰이 빈약하면 한 문장으로 충분하다. 군더더기 금지.

[최근 사고 기록]
{thoughts}
"""


class ReflectionJournaler:
    """자기 성찰 저널 (Tier 3 D2).

    LTM의 사고 로그(source="thought")를 읽어 메타 성찰을 LLM으로 작성하고,
    저널 항목(source="journal")으로 LTM에 남긴다. 저널은 일반 기억처럼 회상되어
    이후 사고에 은근히 반영된다. InnerThoughtEngine과 동일한 단발 호출 패턴.
    """

    def __init__(
        self,
        model: ModelConfig,
        memory: "MemoryService",
        scan_limit: int = 40,
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        self._model = model
        self._memory = memory
        self._scan_limit = scan_limit
        self._prompt = prompt

    async def write(self, scope: "MemoryScope") -> str | None:
        entries = await self._memory.recent(scope, limit=self._scan_limit)
        thoughts = [e.content for e in entries if e.source == THOUGHT_SOURCE]
        if not thoughts:
            return None

        rendered = self._prompt.format(thoughts="\n".join(f"- {t}" for t in thoughts))
        try:
            msg = await stream_to_message(
                self._model,
                LLMContext(messages=[UserMessage(content=rendered)], tools=None),
                StreamOptions(),
            )
            text = msg.text().strip()
        except Exception:
            return None
        if not text:
            return None

        try:
            await self._memory.remember(text, source=JOURNAL_SOURCE, scope=scope)
        except Exception:
            return text  # 저장 실패해도 작성 내용은 반환
        return text

    async def recent(self, scope: "MemoryScope", limit: int = 5) -> list[str]:
        entries = await self._memory.recent(scope, limit=self._scan_limit)
        journal = [e.content for e in entries if e.source == JOURNAL_SOURCE]
        return journal[:limit]
