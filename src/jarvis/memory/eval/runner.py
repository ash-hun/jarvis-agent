"""사례를 대상에 넣고 질의해 판정한다. 사례마다 저장소를 비우므로 실행 순서에 의존하지 않는다."""

from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis.memory.eval.metrics import CaseResult, SuiteReport, judge, summarize
from jarvis.memory.eval.schema import EvalCase, WorkingCase, load_cases, load_working_cases
from jarvis.memory.eval.target import EvalTarget, WorkingTarget
from jarvis.memory.working.window import SUMMARY_HEADER
from jarvis.model_layer.types import Message

DATASETS_DIR = Path(__file__).parent / "datasets"
STORE_SUITES = ("isolation", "semantic", "episodic", "procedural")
WORKING_SUITES = ("working",)
SUITES = STORE_SUITES + WORKING_SUITES


@dataclass
class EvalReport:
    cases: list[CaseResult]
    suites: dict[str, SuiteReport]
    injected_chars: int = 0  # 회상 결과 총 글자 수. 주입 토큰의 근사치
    llm_calls: int = 0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.cases)

    def to_dict(self) -> dict:
        return {
            "suites": {k: asdict(v) for k, v in self.suites.items()},
            "cases": [asdict(c) for c in self.cases],
            "injected_chars": self.injected_chars,
            "llm_calls": self.llm_calls,
        }


def load_suites(names: list[str]) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for name in names:
        if name in STORE_SUITES:
            cases.extend(load_cases(DATASETS_DIR / f"{name}.jsonl"))
    return cases


def load_working_suites(names: list[str]) -> list[WorkingCase]:
    cases: list[WorkingCase] = []
    for name in names:
        if name in WORKING_SUITES:
            cases.extend(load_working_cases(DATASETS_DIR / f"{name}.jsonl"))
    return cases


async def run(cases: list[EvalCase], target: EvalTarget) -> EvalReport:
    results: list[CaseResult] = []
    injected = 0
    for case in cases:
        await target.reset()
        for step in case.setup:
            await target.setup(step, case.step_scope(step))
        found = await target.probe(case.probe, case.scope.to_scope(), case.expect.top_k, case.probe_kind)
        injected += sum(len(s) for s in found)
        results.append(judge(case, found))
    return EvalReport(cases=results, suites=summarize(results), injected_chars=injected)


async def run_working(cases: list[WorkingCase], target: WorkingTarget | None = None) -> EvalReport:
    target = target or WorkingTarget()
    results = []
    for case in cases:
        calls, contexts = await target.run_case(case)
        results.append(judge_working(case, calls, contexts))
    return EvalReport(cases=results, suites=summarize(results), llm_calls=target.calls)


def judge_working(case: WorkingCase, calls: list[int], contexts: list[list[Message]]) -> CaseResult:
    e = case.expect
    problems: list[str] = []
    if calls != e.summarizer_calls:
        problems.append(f"summarizer_calls={calls} expected={e.summarizer_calls}")
    if e.max_messages is not None:
        worst = max(len(c) for c in contexts)
        if worst > e.max_messages:
            problems.append(f"max_messages={worst} > {e.max_messages}")
    has_summary = [bool(c) and _is_summary(c[0]) for c in contexts]
    expected = [e.summary_from_turn is not None and t >= e.summary_from_turn for t in range(len(contexts))]
    if has_summary != expected:
        problems.append(f"summary_present={has_summary} expected={expected}")
    if e.first_role is not None:
        body = [m for m in contexts[-1] if not _is_summary(m)]
        first = body[0].role if body else None
        if first != e.first_role:
            problems.append(f"first_role={first} expected={e.first_role}")
    return CaseResult(
        suite=case.suite,
        case=case.case,
        passed=not problems,
        results=[f"calls={calls}", f"sizes={[len(c) for c in contexts]}"],
        detail="; ".join(problems),
    )


def _is_summary(message: Message) -> bool:
    return message.role == "user" and isinstance(message.content, str) and message.content.startswith(SUMMARY_HEADER)


def merge(*reports: EvalReport) -> EvalReport:
    cases = [c for r in reports for c in r.cases]
    return EvalReport(
        cases=cases,
        suites=summarize(cases),
        injected_chars=sum(r.injected_chars for r in reports),
        llm_calls=sum(r.llm_calls for r in reports),
    )


def format_report(report: EvalReport, verbose: bool = False) -> str:
    lines = [f"{'suite':<12}{'pass':>8}{'recall':>9}{'leak':>8}{'abstain':>9}"]
    for s in report.suites.values():
        lines.append(
            f"{s.suite:<12}{f'{s.passed}/{s.total}':>8}"
            f"{_fmt(s.recall):>9}{_fmt(s.leak_rate):>8}{_fmt(s.abstain_rate):>9}"
        )
    lines.append(f"injected_chars={report.injected_chars} llm_calls={report.llm_calls}")
    if verbose:
        for c in report.cases:
            if c.passed:
                continue
            why = []
            if c.missing:
                why.append(f"missing={c.missing}")
            if c.leaked:
                why.append(f"leaked={c.leaked}")
            if c.broke_abstain:
                why.append("expected empty")
            if c.detail:
                why.append(c.detail)
            lines.append(f"  FAIL {c.suite}/{c.case}: {' '.join(why)}")
    return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"
