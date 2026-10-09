"""사례 판정과 스위트 집계."""

from dataclasses import dataclass, field

from jarvis.memory.eval.schema import EvalCase


@dataclass
class CaseResult:
    suite: str
    case: str
    passed: bool
    results: list[str]
    missing: list[str] = field(default_factory=list)  # contains 중 못 찾은 것
    leaked: list[str] = field(default_factory=list)  # not_contains 중 나온 것
    broke_abstain: bool = False  # empty 기대인데 결과가 있었음


def judge(case: EvalCase, results: list[str]) -> CaseResult:
    top = results[: case.expect.top_k]
    joined = "\n".join(top)
    missing = [s for s in case.expect.contains if s not in joined]
    leaked = [s for s in case.expect.not_contains if s in joined]
    broke_abstain = case.expect.empty and bool(top)
    return CaseResult(
        suite=case.suite,
        case=case.case,
        passed=not missing and not leaked and not broke_abstain,
        results=top,
        missing=missing,
        leaked=leaked,
        broke_abstain=broke_abstain,
    )


@dataclass
class SuiteReport:
    suite: str
    total: int
    passed: int
    recall: float | None  # contains 가 있는 사례 중 전부 찾은 비율
    leak_rate: float | None  # not_contains 가 있는 사례 중 하나라도 샌 비율
    abstain_rate: float | None  # empty 기대 사례 중 실제로 비어 있던 비율


def _ratio(hits: int, total: int) -> float | None:
    return None if total == 0 else hits / total


def summarize(cases: list[EvalCase], results: list[CaseResult]) -> dict[str, SuiteReport]:
    by_suite: dict[str, list[tuple[EvalCase, CaseResult]]] = {}
    for c, r in zip(cases, results, strict=True):
        by_suite.setdefault(c.suite, []).append((c, r))

    reports: dict[str, SuiteReport] = {}
    for suite, pairs in by_suite.items():
        with_contains = [r for c, r in pairs if c.expect.contains]
        with_not = [r for c, r in pairs if c.expect.not_contains]
        with_empty = [r for c, r in pairs if c.expect.empty]
        reports[suite] = SuiteReport(
            suite=suite,
            total=len(pairs),
            passed=sum(r.passed for _, r in pairs),
            recall=_ratio(sum(not r.missing for r in with_contains), len(with_contains)),
            leak_rate=_ratio(sum(bool(r.leaked) for r in with_not), len(with_not)),
            abstain_rate=_ratio(sum(not r.broke_abstain for r in with_empty), len(with_empty)),
        )
    return reports
