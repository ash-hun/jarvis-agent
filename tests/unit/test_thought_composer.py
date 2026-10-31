"""thought 의 composer: 프레임을 메인 프롬프트에 넣을 글로 바꾸는 두 방식을 검증한다."""

from jarvis.agent_layer.thought import DefaultThoughtComposer, InterpretationOnlyComposer, ThoughtFrame, ThoughtComposer


def test_default_composer_uses_context_block():
    frame = ThoughtFrame(interpretation="의도", recalled=["기억"])

    out = DefaultThoughtComposer().compose(frame)

    assert "[내적 사고]" in out and "의도" in out and "기억" in out


def test_interpretation_only_composer_is_lean_and_empty_without_interpretation():
    frame = ThoughtFrame(interpretation="의도", recalled=["기억"], options=["A", "B"])

    out = InterpretationOnlyComposer().compose(frame)

    assert out == "[내적 사고] 의도"
    assert InterpretationOnlyComposer().compose(ThoughtFrame()) == ""


def test_thought_composer_base_uses_context_block():
    frame = ThoughtFrame(interpretation="해석", recalled=["기억"])

    assert ThoughtComposer().compose(frame) == frame.context_block()
    assert isinstance(InterpretationOnlyComposer(), ThoughtComposer)
