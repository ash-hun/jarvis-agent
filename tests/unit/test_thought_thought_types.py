"""thought 의 ThoughtFrame: 기본값이 침묵이고 메인 프롬프트용 블록에 해석과 회상이 실린다."""

from jarvis.agent_layer.thought import ThoughtFrame


def test_frame_defaults_to_silent():
    frame = ThoughtFrame()

    assert frame.decision == "silent"
    assert frame.confidence == 0.0
    assert frame.proactive_actions == []


def test_context_block_includes_interpretation_and_recall():
    frame = ThoughtFrame(interpretation="진짜 의도", recalled=["기억1", "기억2"])

    block = frame.context_block()

    assert "[내적 사고]" in block
    assert "진짜 의도" in block
    assert "기억1" in block and "기억2" in block
