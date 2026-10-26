"""[voice] JARVIS 의 한국어 답을 JARVIS 목소리(영어 TTS)로 읽으려고 소리로만 짧은 영어 구어체로 옮긴다."""

import asyncio
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from jarvis.voice.service import is_english
from jarvis.memory.scope import MAIN_AGENT

if TYPE_CHECKING:
    from jarvis.model_layer.types import ModelConfig

# 화면이 말로 받은 요청의 답을 읽을 때 붙이는 source. 🔔, 승인 질문, filler 는 지금처럼 원문으로 읽는다
SPOKEN_SOURCES = frozenset({"reply", "answer"})
TIMEOUT_SEC = 8.0
# 길게 옮기면 읽는 데 오래 걸린다. 긴 답은 요점만
MAX_WORDS = 45

_PROMPT = """\
You are J.A.R.V.I.S., Tony Stark's AI butler. Below is your reply to the user, written in Korean.
Say it out loud in English, the way JARVIS would speak it: calm, polite British butler, address the user as "sir".
- At most two short sentences and {max_words} words. If the reply is long, give only the conclusion and the key numbers.
- Keep names, numbers, dates and times exact. Spoken words only: no lists, markdown, emoji, URLs or code.
- Output only the English line, nothing else.

Korean reply:
{text}"""

Translate = Callable[[str], Awaitable[str | None]]


def should_speak_english(text: str, source: str, agent_id: str) -> bool:
    """JARVIS 가 말로 받은 요청에 한 한국어 답만 옮긴다. KAREN 등 다른 에이전트는 JARVIS 목소리로 읽지 않는다."""
    return agent_id == MAIN_AGENT and source in SPOKEN_SOURCES and bool(text.strip()) and not is_english(text)


def clean_english(raw: str) -> str | None:
    """모델 답에서 읽을 영어 한 줄. 따옴표를 벗기고, 영어가 아니면(한글이 섞이면) None. 순수 함수."""
    line = " ".join(raw.split()).strip().strip('"').strip("“”").strip()
    return line if line and is_english(line) else None


def make_llm_translator(model: "ModelConfig", timeout: float = TIMEOUT_SEC) -> Translate:
    """실패, 시간 초과, 영어가 아닌 답은 None. 부른 쪽이 원문으로 읽는다."""

    async def translate(text: str) -> str | None:
        from jarvis.model_layer.types import LLMContext, StreamOptions, UserMessage
        from jarvis.model_layer.stream import stream_to_message

        prompt = _PROMPT.format(text=text, max_words=MAX_WORDS)
        ctx = LLMContext(messages=[UserMessage(content=prompt)], tools=None)
        try:
            msg = await asyncio.wait_for(stream_to_message(model, ctx, StreamOptions()), timeout)
        except Exception:
            return None
        return clean_english(msg.text() or "")

    return translate
