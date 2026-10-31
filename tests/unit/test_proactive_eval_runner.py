"""proactive_eval: 사례 판정, 쿨다운 시뮬레이션, 엔진 없는 실행의 결정성, 지표 집계와 보고서를 검증한다."""

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
from jarvis.core.proactive.proactive_types import ProactiveDecision
from jarvis.agent_layer.thought.thought_types import ThoughtFrame


class _ScriptedEngine:
    def __init__(self, frame):
        self.frame = frame
        self.requests = []

    async def think(self, request):
        self.requests.append(request)
        return self.frame


SITUATION_CASE = ProactiveCase(
    suite="situation",
    case="c",
    situation=Situation(
        history=[{"role": "user", "text": "안녕"}, {"role": "assistant", "text": "네"}], open_loops=["보고"]
    ),
    expect=ProactiveExpect(speak=True, mentions=["보고"]),
)


def test_load_suites_parses_bundled_datasets():
    cases = load_suites(list(SUITES))

    assert all((DATASETS_DIR / f"{suite}.jsonl").exists() for suite in SUITES)
    assert len(cases) >= 10
    assert all(c.frame is not None or c.situation is not None for c in cases)


def test_judge_case_checks_speak_mentions_and_risk_split():
    case = ProactiveCase(
        suite="policy", case="c", frame={},
        expect=ProactiveExpect(speak=True, mentions=["배포"], autonomous_tools=["read_file"], approval_tools=["bash"]),
    )

    result = judge_case(case, ProactiveDecision(speak=True, message="배포 상기", reason="gated-pass"))
    silent = judge_case(case, ProactiveDecision(speak=False, reason="cooldown"))

    assert not result.passed
    assert "'read_file' not autonomous" in result.detail and "'bash' not approval" in result.detail
    assert not silent.passed and silent.detail.startswith("speak=False expected=True") and silent.missing == []


def test_build_policy_simulates_prior_speech_against_cooldown():
    case = ProactiveCase(
        suite="policy", case="c", frame={}, policy=PolicySpec(cooldown_sec=100, spoke_before_sec=10),
        expect=ProactiveExpect(speak=False),
    )
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="x")
    within = build_policy(case, now=1000.0).decide_proactive(frame, session_id="eval", now=1000.0).speak

    case.policy.spoke_before_sec = 200

    assert within is False
    assert build_policy(case, now=1000.0).decide_proactive(frame, session_id="eval", now=1000.0).speak is True


async def test_run_cases_policy_suite_passes_offline_and_is_deterministic():
    cases = load_suites(["policy"])

    first = await run_cases(cases)
    second = await run_cases(cases)

    assert first.all_passed
    assert first.to_dict() == second.to_dict()
    metrics = first.suites()["policy"]
    assert metrics.skipped == 0 and metrics.false_alarm_rate == 0.0
    assert metrics.precision == 1.0 and metrics.recall == 1.0


async def test_run_cases_skips_situation_cases_without_engine():
    report = await run_cases(load_suites(["situation"]))

    assert all(r.skipped and r.actual_speak is None for r in report.results)
    assert report.all_passed
    assert report.suites()["situation"].precision is None


async def test_run_cases_sends_reflection_request_and_treats_no_frame_as_silent():
    engine = _ScriptedEngine(ThoughtFrame(decision="act", confidence=0.9, utterance="보고 상기"))

    report = await run_cases([SITUATION_CASE], engine=engine)

    assert report.all_passed and not report.results[0].skipped
    request = engine.requests[0]
    assert request.mode == "reflection" and request.open_loops == ["보고"] and len(request.history) == 2
    assert request.history[1].role == "assistant"
    report = await run_cases([SITUATION_CASE], engine=_ScriptedEngine(None))
    assert report.results[0].actual_speak is False and report.results[0].reason == "no frame"


def test_to_request_is_pure():
    situation = Situation(external_events=["e"], user_model="m")

    assert to_request(situation).model_dump() == to_request(situation).model_dump()


async def test_format_report_lists_skipped_cases():
    report = await run_cases(load_suites(list(SUITES)))

    text = format_report(report, verbose=True)

    assert "policy" in text and "SKIP situation/" in text
