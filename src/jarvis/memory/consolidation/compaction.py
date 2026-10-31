"""[memory] 메시지 묶음(과 이전 요약)을 한 단락으로 줄이는 컴팩션 요약기로, 실패하면 None 이다."""

import re
from collections.abc import Awaitable, Callable

from jarvis.model_layer.model_types import LLMContext, Message, ModelConfig, StreamOptions, UserMessage

# (요약할 메시지, 이전 요약) → 새 요약. None 이면 호출자가 압축을 건너뛴다.
Summarizer = Callable[[list[Message], str | None], Awaitable[str | None]]

# 요약은 장기 기억으로도 저장되고 낱말로 다시 찾는다. 영어 지시문이면 한국어 대화도 영어로 요약돼
# 한국어 질문이 요약에 닿지 않았다. 반대로 "대화 언어로" 만 적으면 한국어 지시문에 끌려 영어 대화를
# 한국어로 요약했다. 그래서 언어는 코드가 대화 글자로 정해 지시문에 못 박는다
SYSTEM_PROMPT = (
    "너는 대화 요약기다. 핵심 사실, 결정, 맥락을 빠짐없이 촘촘하게 요약한다.\n"
    "- 이름, 숫자, 날짜, 요일, 금액, 고유명사, 코드와 명령은 대화에 나온 표기 그대로 남긴다\n"
    "- 요약 문장만 쓴다. 머리말이나 맺음말을 붙이지 않는다"
)
LANGUAGE_RULE = {
    "ko": "- 요약은 반드시 한국어로 쓴다",
    "en": "- Write the summary in English only. (요약은 반드시 영어로 쓴다)",
}
HANGUL_WEIGHT = 10
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_LATIN = re.compile(r"[A-Za-z]")


def conversation_language(messages: list[Message]) -> str:
    """대화에 주로 쓰인 언어(ko 또는 en). 순수 함수다.

    한글 한 글자는 라틴 글자 두세 개만큼의 말을 담고, 한국어 개발 대화에는 코드와 영어 낱말이 많다. 그래서
    한글이 라틴 글자의 1/10 만 있어도 한국어로 본다. 영어 대화에는 한글이 거의 없다
    """
    # 어시스턴트 메시지의 JSON 키("type", "text")가 라틴 글자로 세이지 않게 글 본문만 본다
    text = " ".join(m.content if isinstance(m.content, str) else _plain(m) for m in messages)
    return "ko" if len(_HANGUL.findall(text)) * HANGUL_WEIGHT >= max(len(_LATIN.findall(text)), 1) else "en"


def _plain(message: Message) -> str:
    text = getattr(message, "text", None)
    return text() if callable(text) else ""


def system_prompt_for(messages: list[Message]) -> str:
    return f"{SYSTEM_PROMPT}\n{LANGUAGE_RULE[conversation_language(messages)]}"


def render_messages(messages: list[Message]) -> str:
    return "\n".join(
        f"[{m.role}] " + (m.content if isinstance(m.content, str) else m.model_dump_json()) for m in messages
    )


async def summarize_messages(model: ModelConfig, messages: list[Message], prior: str | None = None) -> str | None:
    """LLM 한 번으로 요약. prior 가 있으면 그 요약을 잇는다. provider 에러면 None."""
    from jarvis.model_layer.stream import stream_to_message

    head = f"이전 요약:\n{prior}\n\n" if prior else ""
    ctx = LLMContext(
        messages=[UserMessage(content=f"{head}다음 대화를 요약하라:\n\n{render_messages(messages)}")],
        system_prompt=system_prompt_for(messages),
    )
    result = await stream_to_message(model, ctx, StreamOptions())
    if result.error_message is not None:
        return None
    return result.text().strip() or "[summary unavailable]"


def llm_summarizer(model: ModelConfig) -> Summarizer:
    async def summarize(messages: list[Message], prior: str | None) -> str | None:
        return await summarize_messages(model, messages, prior)

    return summarize
