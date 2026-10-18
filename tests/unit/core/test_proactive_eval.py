"""proactive 평가: 사례 형식, 정책 판정, 쿨다운 시뮬레이션, 엔진 없는 실행의 결정성, 지표 집계."""

import pytest

from jarvis.core.proactive.eval import (
    DATASETS_DIR,
    SUITES,
    PolicySpec,
    ProactiveCase,
    ProactiveExpect,
    Situation,
    format_report,
    judge_case,
    load_suites,
    run_cases,
)
from jarvis.core.proactive.eval.runner import build_policy, to_request
from jarvis.agent_layer.thought.types import ThoughtFrame
from jarvis.core.proactive.types import ProactiveDecision
from jarvis.core.proactive.eval.__main__ import main


def test_datasets_exist_and_parse():
    for suite in SUITES:
        assert (DATASETS_DIR / f"{suite}.jsonl").exists()
    cases = load_suites(list(SUITES))
    assert len(cases) >= 10
    assert all(c.frame is not None or c.situation is not None for c in cases)


def test_case_requires_frame_or_situation():
    with pytest.raises(ValueError):
        ProactiveCase(suite="x", case="c", expect=ProactiveExpect(speak=False))


def test_judge_case_checks_speak_mentions_and_risk_split():
    case = ProactiveCase(
        suite="policy", case="c", frame={},
        expect=ProactiveExpect(speak=True, mentions=["배포"], autonomous_tools=["read_file"], approval_tools=["bash"]),
    )
    decision = ProactiveDecision(speak=True, message="배포 상기", reason="gated-pass")
    result = judge_case(case, decision)
    assert not result.passed
    assert "'read_file' not autonomous" in result.detail and "'bash' not approval" in result.detail

    silent = judge_case(case, ProactiveDecision(speak=False, reason="cooldown"))
    assert not silent.passed and silent.detail.startswith("speak=False expected=True") and silent.missing == []


def test_build_policy_simulates_prior_speech():
    case = ProactiveCase(
        suite="policy", case="c", frame={}, policy=PolicySpec(cooldown_sec=100, spoke_before_sec=10),
        expect=ProactiveExpect(speak=False),
    )
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="x")
    assert build_policy(case, now=1000.0).decide_proactive(frame, session_id="eval", now=1000.0).speak is False
    case.policy.spoke_before_sec = 200
    assert build_policy(case, now=1000.0).decide_proactive(frame, session_id="eval", now=1000.0).speak is True


async def test_policy_suite_passes_offline_and_is_deterministic():
    cases = load_suites(["policy"])
    first = await run_cases(cases)
    second = await run_cases(cases)
    assert first.all_passed
    assert first.to_dict() == second.to_dict()
    metrics = first.suites()["policy"]
    assert metrics.skipped == 0 and metrics.false_alarm_rate == 0.0
    assert metrics.precision == 1.0 and metrics.recall == 1.0


async def test_situation_cases_skip_without_engine():
    report = await run_cases(load_suites(["situation"]))
    assert all(r.skipped and r.actual_speak is None for r in report.results)
    assert report.all_passed  # 건너뜀은 실패가 아니다
    assert report.suites()["situation"].precision is None


class _ScriptedEngine:
    def __init__(self, frame):
        self.frame = frame
        self.requests = []

    async def think(self, request):
        self.requests.append(request)
        return self.frame


async def test_situation_cases_use_engine_and_reflection_request():
    case = ProactiveCase(
        suite="situation", case="c",
        situation=Situation(
            history=[{"role": "user", "text": "안녕"}, {"role": "assistant", "text": "네"}], open_loops=["보고"]
        ),
        expect=ProactiveExpect(speak=True, mentions=["보고"]),
    )
    engine = _ScriptedEngine(ThoughtFrame(decision="act", confidence=0.9, utterance="보고 상기"))
    report = await run_cases([case], engine=engine)
    assert report.all_passed and not report.results[0].skipped
    request = engine.requests[0]
    assert request.mode == "reflection" and request.open_loops == ["보고"] and len(request.history) == 2
    assert request.history[1].role == "assistant"

    none_engine = _ScriptedEngine(None)
    report = await run_cases([case], engine=none_engine)
    assert report.results[0].actual_speak is False and report.results[0].reason == "no frame"


def test_to_request_is_pure():
    situation = Situation(external_events=["e"], user_model="m")
    assert to_request(situation).model_dump() == to_request(situation).model_dump()


async def test_format_report_lists_skips():
    report = await run_cases(load_suites(list(SUITES)))
    text = format_report(report, verbose=True)
    assert "policy" in text and "SKIP situation/" in text


def test_cli_offline(capsys):
    assert main(["--suite", "policy"]) == 0
    assert main(["--json", "--suite", "policy"]) == 0
    assert '"suites"' in capsys.readouterr().out
