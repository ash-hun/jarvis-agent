"""proactive_eval: 평가 사례가 사고 프레임이나 상황 중 하나를 꼭 갖는지 검증한다."""

import pytest

from jarvis.core.proactive.eval import ProactiveCase, ProactiveExpect


def test_case_without_frame_or_situation_is_rejected():
    with pytest.raises(ValueError):
        ProactiveCase(suite="x", case="c", expect=ProactiveExpect(speak=False))


@pytest.mark.parametrize(
    ("label", "speak", "expected"),
    [("can", False, "can"), (None, True, "must"), (None, False, "must_not")],
    ids=["explicit", "speak_true", "speak_false"],
)
def test_effective_label_falls_back_to_expect_speak(label, speak, expected):
    case = ProactiveCase(suite="s", case="c", label=label, frame={}, expect=ProactiveExpect(speak=speak))

    assert case.effective_label == expected
