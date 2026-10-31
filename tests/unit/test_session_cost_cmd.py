"""session 의 /cost: 모델명으로 단가를 고르고, 세션 사용량을 모델별로 합산해 추정 비용을 보고하는지 검증한다."""

import pytest

from jarvis.model_layer.model_types import AssistantMessage, TextContent, Usage, UserMessage
from jarvis.core.slash.cost_cmd import cost_rate, estimate_cost, make_cost_handler


def _assistant(model: str, inp: int, out: int) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text="a")], model=model, usage=Usage(input=inp, output=out))


@pytest.mark.parametrize(
    ("model", "rate"),
    [
        ("claude-opus-4", (15.0, 75.0)),
        ("claude-sonnet-4-5", (3.0, 15.0)),
        ("claude-haiku-4-5", (0.8, 4.0)),
        ("gemini-2.0", (1.25, 5.0)),
        ("gpt-4o-mini", (0.15, 0.6)),  # gpt-4o 보다 먼저 맞아야 한다
        ("gpt-4o", (5.0, 15.0)),
        ("mystery-model", (3.0, 15.0)),
        ("", (3.0, 15.0)),
    ],
)
def test_cost_rate_matches_model_substring_or_default(model, rate):
    assert cost_rate(model) == rate


@pytest.mark.parametrize(
    ("model", "inp", "out", "usd"),
    [("claude-sonnet-4-5", 1_000_000, 1_000_000, 18.0), ("claude-opus-4", 100_000, 0, 1.5)],
)
def test_estimate_cost_uses_per_million_rates(model, inp, out, usd):
    assert estimate_cost(model, inp, out) == pytest.approx(usd)


async def test_cost_aggregates_usage_per_model(jsonl_repo):
    await jsonl_repo.create(session_id="default")
    await jsonl_repo.append("default", UserMessage(content="hi"))
    await jsonl_repo.append("default", _assistant("claude-sonnet-4-5", 1000, 500))
    await jsonl_repo.append("default", _assistant("claude-sonnet-4-5", 2000, 800))
    await jsonl_repo.append("default", _assistant("gpt-4o-mini", 5000, 200))

    out = await make_cost_handler(jsonl_repo)("")

    assert "claude-sonnet-4-5" in out and "gpt-4o-mini" in out
    assert "3,000" in out  # sonnet 입력 1000+2000
    assert "$" in out and "합계" in out


async def test_cost_reports_nothing_for_session_without_replies(jsonl_repo):
    await jsonl_repo.create(session_id="default")

    out = await make_cost_handler(jsonl_repo)("")

    assert "집계할 사용량이 없습니다" in out
