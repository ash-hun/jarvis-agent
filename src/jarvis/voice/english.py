"""[voice] JARVIS 가 소리 내는 한국어 글을 JARVIS 목소리(영어 TTS)로 읽으려고 소리로만 짧은 영어 구어체로 옮긴다."""

import asyncio
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from jarvis.voice.service import is_english
from jarvis.memory.scope import MAIN_AGENT

if TYPE_CHECKING:
    from jarvis.model_layer.types import ModelConfig

TIMEOUT_SEC = 8.0
# 옮기지 못했을 때 읽는 말. 한국어 원문을 다른 목소리로 읽지 않고 화면을 보게 한다
FALLBACK_LINE = "Sir, I've put it on your screen."
# 길게 옮기면 읽는 데 오래 걸린다. 긴 답은 요점만
MAX_WORDS = 45

_PROMPT = """\
You are J.A.R.V.I.S., Tony Stark's AI butler. Below is what you are about to say to the user, written in Korean.
Say it out loud in English, the way JARVIS would speak it: calm, polite British butler, address the user as "sir".
- At most two short sentences and {max_words} words. If it is long, give only the conclusion and the key numbers.
- Keep names, numbers, dates and times exact. Spoken words only: no lists, markdown, emoji, URLs or code.
- Output only the English line, nothing else.

Korean:
{text}"""

Translate = Callable[[str], Awaitable[str | None]]


def should_speak_english(text: str, agent_id: str) -> bool:
    """JARVIS 가 내는 한국어 글은 무엇이든(답, 🔔, filler, 앞으로 생길 종류) 옮긴다. KAREN 등은 원문 그대로."""
    return agent_id == MAIN_AGENT and bool(text.strip()) and not is_english(text)


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
