"""proactive_eval: 평가 사례가 사고 프레임이나 상황 중 하나를 꼭 갖는지 검증한다."""

import pytest

from jarvis.core.proactive.eval import ProactiveCase, ProactiveExpect


def test_case_without_frame_or_situation_is_rejected():
    with pytest.raises(ValueError):
        ProactiveCase(suite="x", case="c", expect=ProactiveExpect(speak=False))
