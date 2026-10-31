"""컴팩션 충실도: 심은 사실의 보존율. 추출 기준선은 전부 보존하고, 사실을 버리는 요약기는 실패한다."""

import pytest

from jarvis.memory.eval.faithfulness import (
    contains_fact_judge,
    extractive_summarizer,
    load_faithfulness_cases,
    run_faithfulness,
)
from jarvis.memory.eval.runner import DATASETS_DIR, SUITES, format_report, run_faithfulness_suite


@pytest.mark.memory_eval
async def test_extractive_baseline_keeps_every_planted_fact():
    cases = load_faithfulness_cases(DATASETS_DIR / "faithfulness.jsonl")
    assert cases and "faithfulness" in SUITES
    results = await run_faithfulness(cases, extractive_summarizer(), contains_fact_judge())
    assert all(r.passed for r in results), [(r.case, r.detail, r.missing) for r in results]
    assert all(r.score == 1.0 for r in results)


async def test_lossy_summarizer_fails_and_reports_missing_facts():
    cases = load_faithfulness_cases(DATASETS_DIR / "faithfulness.jsonl")

    async def lossy(messages, prior):
        return "요약: 사용자가 이것저것 말했다. 거주지는 부산."  # 사실 하나만 남긴다

    results = await run_faithfulness(cases[:1], lossy, contains_fact_judge())
    r = results[0]
    assert not r.passed and r.score == 0.25 and set(r.missing) == {"보리", "금요일", "커피"}
    assert "retention=0.25" in r.detail


async def test_no_summary_is_a_failure_not_a_pass():
    cases = load_faithfulness_cases(DATASETS_DIR / "faithfulness.jsonl")

    async def silent(messages, prior):
        return None

    (r,) = await run_faithfulness(cases[:1], silent, contains_fact_judge())
    assert not r.passed and r.detail == "no summary"


async def test_suite_report_has_mean_score_column():
    report = await run_faithfulness_suite(["faithfulness"])
    assert report is not None and report.suites["faithfulness"].mean_score == 1.0
    text = format_report(report)
    assert "score" in text.splitlines()[0] and "1.00" in text
    assert await run_faithfulness_suite(["semantic"]) is None
