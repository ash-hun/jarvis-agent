"""사례를 대상에 넣고 질의해 판정한다. 사례마다 저장소를 비우므로 실행 순서에 의존하지 않는다."""

from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis.memory.eval.metrics import CaseResult, SuiteReport, judge, summarize
from jarvis.memory.eval.schema import EvalCase, load_cases
from jarvis.memory.eval.target import EvalTarget

DATASETS_DIR = Path(__file__).parent / "datasets"
SUITES = ("isolation", "semantic")


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
        cases.extend(load_cases(DATASETS_DIR / f"{name}.jsonl"))
    return cases


async def run(cases: list[EvalCase], target: EvalTarget) -> EvalReport:
    results: list[CaseResult] = []
    injected = 0
    for case in cases:
        await target.reset()
        for step in case.setup:
            await target.setup(step, case.step_scope(step))
        found = await target.probe(case.probe, case.scope.to_scope(), case.expect.top_k)
        injected += sum(len(s) for s in found)
        results.append(judge(case, found))
    return EvalReport(cases=results, suites=summarize(cases, results), injected_chars=injected)


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
            lines.append(f"  FAIL {c.suite}/{c.case}: {' '.join(why)}")
    return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"

