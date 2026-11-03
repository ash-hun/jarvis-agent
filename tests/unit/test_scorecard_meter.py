"""스코어카드 계량기: 예산 모델의 실제 비용이 상한에 닿으면 다음 호출 전에 멈춘다."""

import pytest
from scripts.experiments.scorecard_meter import BudgetExhausted, UsageMeter

from jarvis.model_layer.model_types import StopEvent, Usage

PRICES = {"claude": {"input": 3.0, "output": 15.0}}


def test_meter_adds_usage_per_model_and_stops_budget_model_at_cap():
    meter = UsageMeter(PRICES, spent=1.0, cap=7.0)
    meter.add("claude", StopEvent(reason="stop", usage=Usage(input=1_000_000, output=0)))

    meter.check("claude")
    meter.add("claude", StopEvent(reason="stop", usage=Usage(input=1_000_000, output=0)))
    assert meter.usage["claude"]["calls"] == 2 and meter.cost() == 6.0
    with pytest.raises(BudgetExhausted):
        meter.check("claude")


def test_meter_never_stops_models_outside_the_budget_or_without_a_cap():
    meter = UsageMeter(PRICES, spent=100.0, cap=1.0)

    meter.check("gpt-4o-mini")
    UsageMeter().check("claude")
