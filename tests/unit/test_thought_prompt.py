"""thought 의 ThoughtPromptTemplate: 자리 채우기, 에이전트 말투 자리, 파일이 없을 때 기본 템플릿으로 물러나기."""

import pytest

from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE, DEFAULT_TEMPLATE, ThoughtPromptTemplate


def test_render_fills_known_placeholders_and_keeps_unknown():
    tpl = ThoughtPromptTemplate("입력={{user_input}} 시각={{now}} 없음={{missing}}")

    out = tpl.render(user_input="안녕", now="T")

    assert "입력=안녕" in out
    assert "시각=T" in out
    assert "{{missing}}" in out


@pytest.mark.parametrize(
    ("kwargs", "phrases"),
    [({}, ("내적 사고", "ZZZ")), ({"default": DEFAULT_REFLECTION_TEMPLATE}, ("자율 성찰",))],
    ids=["request_default", "custom_default"],
)
def test_load_falls_back_to_default_when_file_missing(tmp_path, kwargs, phrases):
    tpl = ThoughtPromptTemplate.load(str(tmp_path / "missing.md"), **kwargs)

    out = tpl.render(user_input="ZZZ")

    assert all(phrase in out for phrase in phrases)


def test_load_reads_file(tmp_path):
    p = tmp_path / "inner_thought.md"
    p.write_text("커스텀 {{user_input}}", encoding="utf-8")

    tpl = ThoughtPromptTemplate.load(str(p))

    assert tpl.render(user_input="X") == "커스텀 X"


@pytest.mark.parametrize("text", [DEFAULT_TEMPLATE, DEFAULT_REFLECTION_TEMPLATE], ids=["request", "reflection"])
def test_thought_template_has_a_persona_slot(text):
    rendered = ThoughtPromptTemplate(text).render(persona="다정한 말투")

    assert "[말투] 다정한 말투" in rendered and "{{persona}}" not in rendered
