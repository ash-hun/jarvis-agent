"""memory_eval 기능의 비용 계측: 블록 안의 LLM 호출만 센다."""

from jarvis.model_layer.model_types import LLMContext, UserMessage
from jarvis.model_layer.stream import stream_to_message
from jarvis.memory.eval.probe import count_llm_calls


async def test_count_llm_calls_counts_only_inside_the_block(faux_model_with_response):
    model = faux_model_with_response("ok")
    ctx = LLMContext(messages=[UserMessage(content="hi")])

    with count_llm_calls("faux") as counter:
        await stream_to_message(model, ctx)
        await stream_to_message(model, ctx)
    await stream_to_message(model, ctx)

    assert counter.calls == 2
