"""스코어카드 점수 변환, 구간, 비용과 예산 판정."""

from scripts.experiments.scorecard_points import (
    kappa,
    wilson,
    balanced,
    compare_verdicts,
    cost_usd,
    fits_budget,
    estimate_usd,
    vertex_entry,
)


def test_wilson_matches_known_interval_and_handles_empty_sample():
    lo, hi = wilson(0.3, 40)

    assert round(lo, 3) == 0.181 and round(hi, 3) == 0.454
    assert wilson(0.5, 0) == (0.0, 1.0)


def test_vertex_entry_scales_to_hundred_and_balanced_averages_recall_and_restraint():
    entry = vertex_entry(balanced(1.0, 0.4), 20, {"recall": 1.0})

    assert entry["score"] == 80.0 and entry["n"] == 20 and entry["detail"] == {"recall": 1.0}
    assert entry["ci95"][0] < 80.0 < entry["ci95"][1]


def test_cost_counts_cache_tokens_at_their_own_price_or_input_price():
    price = {"input": 3.0, "output": 15.0, "cache_read": 0.3}
    usage = {"input": 1_000_000, "output": 100_000, "cache_read": 1_000_000, "cache_write": 1_000_000}

    assert round(cost_usd(usage, price), 2) == round(3.0 + 1.5 + 0.3 + 3.0, 2)


def test_estimate_ignores_cache_discount_and_budget_stops_at_cap():
    estimate = estimate_usd({"input": 500_000, "cache_read": 500_000, "output": 0}, {"input": 3.0, "output": 15.0}, 1.5)

    assert round(estimate, 2) == 4.5
    assert fits_budget(13.0, 5.0, 18.0) and not fits_budget(13.5, 5.0, 18.0)


def test_kappa_is_one_for_identical_and_zero_for_chance_agreement():
    assert kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert kappa([True, True, False, False], [True, False, True, False]) == 0.0


def test_kappa_is_undefined_for_empty_or_one_sided_verdicts():
    assert kappa([], []) is None
    assert kappa([True, True], [True, True]) is None


def test_compare_replaces_only_llm_judged_verdicts():
    rows = [{"correct": True}, {"correct": False}, {"correct": True}, {"correct": False}]

    out = compare_verdicts(rows, [0, 1], [False, True])

    assert out["original"]["score"] == 50.0 and out["regraded"]["score"] == 50.0
    assert out["llm_judged"] == 2 and out["agreement"] == 0.0
    assert out["yes_to_no"] == 1 and out["no_to_yes"] == 1


def test_compare_without_llm_judged_items_keeps_score_and_has_no_agreement():
    out = compare_verdicts([{"correct": True}, {"correct": False}], [], [])

    assert out["regraded"]["score"] == out["original"]["score"] == 50.0
    assert out["agreement"] is None and out["kappa"] is None
