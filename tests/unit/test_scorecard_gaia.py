"""[tests] GAIA 공식 정규화, 일치 판정, 답 파싱, 표본 고르기와 주소 차단을 검증한다."""

from typing import Any
from scripts.experiments.gaia_bench import allocate, blocked_reason, pick_sample, summarize
from scripts.experiments.gaia_score import (
    normalize_number_str,
    normalize_str,
    parse_final_answer,
    question_scorer,
    split_string,
)


def test_normalize_number_str_strips_units_and_commas() -> None:
    assert normalize_number_str("$1,234.5%") == 1234.5


def test_normalize_number_str_non_number_is_inf() -> None:
    assert normalize_number_str("twelve") == float("inf")


def test_normalize_str_drops_spaces_case_and_punct() -> None:
    assert normalize_str("Sea Gull!") == "seagull"


def test_normalize_str_keeps_punct_when_asked() -> None:
    assert normalize_str("St. Louis", remove_punct=False) == "st.louis"


def test_split_string_on_comma_and_semicolon() -> None:
    assert split_string("a, b; c") == ["a", " b", " c"]


def test_split_string_without_separator() -> None:
    assert split_string("abc") == ["abc"]


def test_question_scorer_number() -> None:
    assert question_scorer("$17,000", "17000")
    assert not question_scorer("17 thousand", "17000")


def test_question_scorer_list() -> None:
    assert question_scorer("apple, 3, Banana", "apple, 3, banana")
    assert not question_scorer("apple, banana", "apple, 3, banana")


def test_question_scorer_list_keeps_punct_in_elements() -> None:
    assert not question_scorer("St Louis, Boston", "St. Louis, Boston")


def test_question_scorer_string() -> None:
    assert question_scorer("the Sea-Gull.", "theseagull")
    assert not question_scorer(None, "seagull")


def test_parse_final_answer_takes_last_line() -> None:
    text = "FINAL ANSWER: 3\nwait, recount.\nFINAL ANSWER: **[42]**"
    assert parse_final_answer(text) == "42"


def test_parse_final_answer_missing() -> None:
    assert parse_final_answer("I could not find it.") is None


def test_parse_final_answer_falls_back_to_overflow_summary() -> None:
    assert parse_final_answer("- 지금까지의 답: Paris") == "Paris"


def _rows() -> list[dict[str, Any]]:
    rows = [{"task_id": f"a{i:02d}", "Level": "1", "file_name": ""} for i in range(10)]
    rows += [{"task_id": f"b{i:02d}", "Level": "2", "file_name": ""} for i in range(20)]
    rows += [{"task_id": "c00", "Level": "1", "file_name": "x.pdf"}, {"task_id": "d00", "Level": "3", "file_name": ""}]
    return rows


def test_allocate_proportional() -> None:
    assert allocate({"1": 42, "2": 66}, 40) == {"1": 16, "2": 24}


def test_allocate_takes_all_when_pool_small() -> None:
    assert allocate({"1": 2, "2": 3}, 40) == {"1": 2, "2": 3}


def test_pick_sample_stratified_and_stable() -> None:
    picked = pick_sample(_rows(), 9, seed=0)
    assert [r["task_id"] for r in picked] == [r["task_id"] for r in pick_sample(list(reversed(_rows())), 9, seed=0)]
    assert sum(r["Level"] == "1" for r in picked) == 3
    assert all(r["file_name"] == "" and r["Level"] in ("1", "2") for r in picked)


def test_pick_sample_empty_pool() -> None:
    assert pick_sample([], 40, seed=0) == []


def test_blocked_reason_allows_public_url() -> None:
    assert blocked_reason("https://en.wikipedia.org/wiki/Seagull") is None


def test_blocked_reason_blocks_private_and_leak() -> None:
    assert blocked_reason("http://127.0.0.1:8000/") is not None
    assert blocked_reason("http://localhost/x") is not None
    assert blocked_reason("https://huggingface.co/datasets/gaia-benchmark/GAIA") is not None


def _row(level: str, correct: bool, error: str | None = None) -> dict[str, Any]:
    return {"level": level, "correct": correct, "predicted": "x", "llm_calls": 2, "input_tokens": 100,
            "output_tokens": 10, "web_requests": 3, "tool_calls": {"web_search": 2}, "overflows": 0,
            "rate_limited": 0, "empty_search": 0, "error": error}


def test_summarize_by_level() -> None:
    out = summarize([_row("1", True), _row("2", False), _row("2", True)])
    assert out["accuracy"] == round(2 / 3, 4)
    assert out["by_level"]["2"] == {"n": 2, "accuracy": 0.5}
    assert out["mean_tool_calls"] == {"web_search": 2.0}


def test_summarize_empty() -> None:
    assert summarize([])["accuracy"] == 0.0
