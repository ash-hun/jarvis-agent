"""컴팩션 요약기. 메시지 묶음(과 이전 요약)을 한 단락으로 줄인다. 실패하면 None."""

from collections.abc import Awaitable, Callable

from jarvis.model_layer.types import LLMContext, Message, ModelConfig, StreamOptions, UserMessage

# (요약할 메시지, 이전 요약) → 새 요약. None 이면 호출자가 압축을 건너뛴다.
Summarizer = Callable[[list[Message], str | None], Awaitable[str | None]]

SYSTEM_PROMPT = (
    "You are a summarization assistant. "
    "Produce a dense summary preserving key facts, decisions, and context."
)


def render_messages(messages: list[Message]) -> str:
    return "\n".join(
        f"[{m.role}] " + (m.content if isinstance(m.content, str) else m.model_dump_json())
        for m in messages
    )


async def summarize_messages(model: ModelConfig, messages: list[Message], prior: str | None = None) -> str | None:
    """LLM 한 번으로 요약. prior 가 있으면 그 요약을 잇는다. provider 에러면 None."""
    from jarvis.model_layer.stream import stream_to_message

    head = f"Previous summary:\n{prior}\n\n" if prior else ""
    ctx = LLMContext(
        messages=[
            UserMessage(content=f"{head}Summarize the following conversation concisely:\n\n{render_messages(messages)}")
        ],
        system_prompt=SYSTEM_PROMPT,
    )
    result = await stream_to_message(model, ctx, StreamOptions())
    if result.error_message is not None:
        return None
    return result.text().strip() or "[summary unavailable]"


def llm_summarizer(model: ModelConfig) -> Summarizer:
    async def summarize(messages: list[Message], prior: str | None) -> str | None:
        return await summarize_messages(model, messages, prior)

    return summarize
