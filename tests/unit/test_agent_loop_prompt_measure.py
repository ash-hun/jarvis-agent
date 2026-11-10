"""agent_loop: LLM 호출 입력을 부분별 글자 수로 나누는 measure_prompt 를 검증한다."""

from jarvis.model_layer.model_types import AssistantMessage, LLMContext, TextContent, Tool, UserMessage
from jarvis.agent_layer.prompt_measure import measure_prompt

TOOL = Tool(name="bash", description="d", parameters={"type": "object", "properties": {}})


def test_splits_system_thought_tools_and_memory_blocks_in_order() -> None:
    context = LLMContext(
        system_prompt="persona\n\nTHOUGHT",
        tools=[TOOL],
        messages=[
            UserMessage(content="[핵심 사실]\n- a"),
            UserMessage(content="[장기 기억]\n- b"),
            UserMessage(content="[장기 기억] - c"),
            UserMessage(content="안녕"),
            AssistantMessage(content=[TextContent(text="네")]),
        ],
    )

    sizes = measure_prompt(context, "THOUGHT")

    assert list(sizes) == ["system", "inner_thought", "tools", "[핵심 사실]", "[장기 기억]", "user", "assistant"]
    assert (sizes["system"], sizes["inner_thought"], sizes["user"]) == (7, 7, 2)
    assert sizes["[장기 기억]"] == len("[장기 기억]\n- b") + len("[장기 기억] - c")
    assert sizes["tools"] > 0 and sizes["assistant"] > 0


def test_empty_context_has_zero_fixed_parts() -> None:
    sizes = measure_prompt(LLMContext(messages=[]))

    assert sizes == {"system": 0, "inner_thought": 0, "tools": 0}
