"""[core] proactive 평가 사례를 사례마다 새 정책과 고정 시계로 판정하고 지표로 요약한다."""

# 공유 상태가 없어 실행 순서와 횟수에 의존하지 않는다.

from typing import Any
from pathlib import Path
from dataclasses import asdict, dataclass, field

from jarvis.model_layer.model_types import AssistantMessage, Message, TextContent, UserMessage
from jarvis.core.proactive.eval.eval_schema import ProactiveCase, Situation, load_cases
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.thought_protocol import ThoughtEngine
from jarvis.core.proactive.proactive_types import ProactiveDecision
from jarvis.core.proactive.policy import DefaultProactivityPolicy

DATASETS_DIR = Path(__file__).parent / "datasets"
SUITES = ("policy", "situation")
FIXED_NOW = 1_000_000.0  # 정책 시계. 실제 시각과 무관해야 같은 사례가 같은 결과를 낸다
SESSION = "eval"
# session.py 의 REFLECTION_SEED 와 같은 뜻. 거기서 import 하면 세션 전체 의존성이 딸려 온다
REFLECTION_INPUT = (
    "(자율 성찰) 지금은 사용자의 직접 요청이 없는 시점이다. 먼저 알릴 가치가 있으면 act/ask, 없으면 silent."
)
PASSING_FRAME = ThoughtFrame(decision="act", confidence=1.0, utterance="prior")


@dataclass
class ProactiveCaseResult:
    suite: str
    case: str
    passed: bool
    expected_speak: bool
    actual_speak: bool | None  # None 이면 건너뜀(엔진 없이 상황 사례)
    reason: str = ""
    message: str = ""
    missing: list[str] = field(default_factory=list)
    detail: str = ""
    skipped: bool = False


@dataclass
class SuiteMetrics:
    suite: str
    total: int
    passed: int
    skipped: int
    precision: float | None  # 말한 것 중 말했어야 한 비율
    recall: float | None  # 말했어야 한 것 중 말한 비율
    false_alarm_rate: float | None  # 침묵했어야 하는데 말한 비율


@dataclass
class ProactiveReport:
    results: list[ProactiveCaseResult]

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results if not r.skipped)

    def suites(self) -> dict[str, SuiteMetrics]:
        by_suite: dict[str, list[ProactiveCaseResult]] = {}
        for r in self.results:
            by_suite.setdefault(r.suite, []).append(r)
        return {name: summarize(name, rs) for name, rs in by_suite.items()}

    def to_dict(self) -> dict[str, Any]:
        return {"suites": {k: asdict(v) for k, v in self.suites().items()}, "cases": [asdict(r) for r in self.results]}


def summarize(suite: str, results: list[ProactiveCaseResult]) -> SuiteMetrics:
    judged = [r for r in results if not r.skipped]
    spoke = [r for r in judged if r.actual_speak]
    should = [r for r in judged if r.expected_speak]
    quiet_expected = [r for r in judged if not r.expected_speak]
    return SuiteMetrics(
        suite=suite,
        total=len(results),
        passed=sum(r.passed for r in judged),
        skipped=len(results) - len(judged),
        precision=_ratio(sum(r.expected_speak for r in spoke), len(spoke)),
        recall=_ratio(sum(bool(r.actual_speak) for r in should), len(should)),
        false_alarm_rate=_ratio(sum(bool(r.actual_speak) for r in quiet_expected), len(quiet_expected)),
    )


def _ratio(hits: int, total: int) -> float | None:
    return None if total == 0 else hits / total


# ── 실행 ──────────────────────────────────────────────────────────────────────


def load_suites(names: list[str]) -> list[ProactiveCase]:
    cases: list[ProactiveCase] = []
    for name in names:
        if name in SUITES:
            cases.extend(load_cases(DATASETS_DIR / f"{name}.jsonl"))
    return cases


def build_policy(case: ProactiveCase, now: float) -> DefaultProactivityPolicy:
    """사례 전용 정책. 직전 발화가 있었다는 사례면 그 시각에 한 번 말한 상태로 만든다."""
    policy = DefaultProactivityPolicy(
        confidence_threshold=case.policy.confidence_threshold,
        cooldown_sec=case.policy.cooldown_sec,
        clock=lambda: now,
    )
    if case.policy.spoke_before_sec is not None:
        policy.decide_proactive(PASSING_FRAME, session_id=SESSION, now=now - case.policy.spoke_before_sec)
        if not case.policy.awaiting_reply:
            policy.note_user_activity(SESSION)
    return policy


def to_request(situation: Situation) -> ThoughtRequest:
    history: list[Message] = []
    for i, turn in enumerate(situation.history):
        if turn.role == "assistant":
            history.append(AssistantMessage(content=[TextContent(text=turn.text)], timestamp=i))
        else:
            history.append(UserMessage(content=turn.text, timestamp=i))
    return ThoughtRequest(
        user_input=REFLECTION_INPUT,
        history=history,
        session_id=SESSION,
        open_loops=situation.open_loops,
        user_model=situation.user_model,
        external_events=situation.external_events,
        mode="reflection",
    )


def judge_case(case: ProactiveCase, decision: ProactiveDecision) -> ProactiveCaseResult:
    problems: list[str] = []
    if decision.speak != case.expect.speak:
        problems.append(f"speak={decision.speak} expected={case.expect.speak}")
    missing = [m for m in case.expect.mentions if m not in decision.message] if decision.speak else []
    if missing:
        problems.append(f"missing={missing}")
    autonomous = {a.tool_name for a in decision.autonomous_actions if a.tool_name}
    approval = {a.tool_name for a in decision.approval_actions if a.tool_name}
    for tool in case.expect.autonomous_tools:
        if tool not in autonomous:
            problems.append(f"'{tool}' not autonomous")
    for tool in case.expect.approval_tools:
        if tool not in approval:
            problems.append(f"'{tool}' not approval")
    return ProactiveCaseResult(
        suite=case.suite,
        case=case.case,
        passed=not problems,
        expected_speak=case.expect.speak,
        actual_speak=decision.speak,
        reason=decision.reason,
        message=decision.message[:200],
        missing=missing,
        detail="; ".join(problems),
    )


async def run_case(case: ProactiveCase, engine: ThoughtEngine | None, now: float) -> ProactiveCaseResult:
    if case.frame is not None:
        frame: ThoughtFrame | None = ThoughtFrame.model_validate(case.frame)
    elif engine is None:
        return ProactiveCaseResult(
            suite=case.suite, case=case.case, passed=True, expected_speak=case.expect.speak,
            actual_speak=None, skipped=True, detail="needs engine",
        )
    else:
        assert case.situation is not None
        frame = await engine.think(to_request(case.situation))
    if frame is None:
        # 엔진이 사고를 생략했거나 파싱에 실패하면 말하지 않은 것이다
        decision = ProactiveDecision(speak=False, reason="no frame")
    else:
        decision = build_policy(case, now).decide_proactive(frame, session_id=SESSION, now=now)
    return judge_case(case, decision)


async def run_cases(
    cases: list[ProactiveCase], engine: ThoughtEngine | None = None, now: float = FIXED_NOW
) -> ProactiveReport:
    return ProactiveReport(results=[await run_case(case, engine, now) for case in cases])


def format_report(report: ProactiveReport, verbose: bool = False) -> str:
    lines = [f"{'suite':<12}{'pass':>8}{'skip':>6}{'prec':>7}{'recall':>8}{'false+':>8}"]
    for s in report.suites().values():
        judged = s.total - s.skipped
        lines.append(
            f"{s.suite:<12}{f'{s.passed}/{judged}':>8}{s.skipped:>6}"
            f"{_fmt(s.precision):>7}{_fmt(s.recall):>8}{_fmt(s.false_alarm_rate):>8}"
        )
    if verbose:
        for r in report.results:
            if r.passed and not r.skipped:
                continue
            tag = "SKIP" if r.skipped else "FAIL"
            lines.append(f"  {tag} {r.suite}/{r.case}: {r.detail} ({r.reason})")
    return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"
