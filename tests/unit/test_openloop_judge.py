"""openloop: AGENDA 판단이 프롬프트에 열린 약속과 입력을 싣고 모델 출력에서 새 약속과 닫을 약속을 읽는지 검증한다."""

import pytest
from datetime import datetime

from jarvis.agent_layer.openloop.judge import LoopVerdict, OpenLoopJudge, parse_verdict, render_prompt
from jarvis.model_layer.model_types import AssistantMessage, TextContent, UserMessage
from jarvis.model_layer.model_registry import get_default_registry
from tests.fixtures.faux_provider import FauxProviderFactory

NOW = datetime(2026, 10, 19, 9, 0)


def test_render_prompt_carries_now_loops_history_and_input():
    history = [UserMessage(content="회의록 맡을게"), AssistantMessage(content=[TextContent(text="알겠어요")])]

    prompt = render_prompt(NOW, "보고서는 취소됐어", ["[1] 분기 보고서 제출"], history)

    assert "[지금] 2026-10-19T09:00:00" in prompt
    assert "- [1] 분기 보고서 제출" in prompt
    assert "user: 회의록 맡을게" in prompt and "assistant: 알겠어요" in prompt
    assert "[사용자 입력] 보고서는 취소됐어" in prompt
    assert "{{" not in prompt


@pytest.mark.parametrize(
    ("raw", "verdict"),
    [
        (
            '```json\n{"open_loops": [{"description": "보고서 보내기", "due": "@2026-10-20 15:00"}],'
            ' "closed_loops": [2]}\n```',
            LoopVerdict(open_loops=["보고서 보내기 @2026-10-20 15:00"], closed_loops=["2"]),
        ),
        ("약속 없음", None),
    ],
)
def test_parse_verdict_tolerates_fences_and_object_items_and_rejects_non_json(raw, verdict):
    assert parse_verdict(raw) == verdict


async def test_judge_reads_model_output(faux_model_with_response):
    model = faux_model_with_response('{"open_loops": ["보고서 보내기"], "closed_loops": []}')

    verdict = await OpenLoopJudge(model, clock=lambda: NOW).judge("내일 보고서 보내야 해", [], [])

    assert verdict == LoopVerdict(open_loops=["보고서 보내기"])


async def test_judge_failure_is_none(monkeypatch, faux_model):
    monkeypatch.setitem(get_default_registry()._providers, "faux", FauxProviderFactory.error())

    assert await OpenLoopJudge(faux_model, clock=lambda: NOW).judge("내일 보고서", [], []) is None
