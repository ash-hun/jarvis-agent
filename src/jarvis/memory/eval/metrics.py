"""[memory] 평가 사례를 기대값으로 판정하고 스위트별 지표로 집계한다."""

from dataclasses import dataclass, field

from jarvis.memory.eval.eval_schema import EvalCase


@dataclass
class CaseResult:
    suite: str
    case: str
    passed: bool
    results: list[str]
    missing: list[str] = field(default_factory=list)  # contains 중 못 찾은 것
    leaked: list[str] = field(default_factory=list)  # not_contains 중 나온 것
    broke_abstain: bool = False  # empty 기대인데 결과가 있었음
    detail: str = ""  # 저장소 밖 스위트(working)의 실패 설명
    # 어느 지표에 포함되는 사례인지. 집계가 사례 정의를 다시 읽지 않도록 판정 시 기록한다
    checks_recall: bool = False
    checks_leak: bool = False
    checks_abstain: bool = False
    score: float | None = None  # 비율형 지표(충실도 retention 등). 스위트 평균으로 집계


def judge(case: EvalCase, results: list[str]) -> CaseResult:
    top = results[: case.expect.top_k]
    joined = "\n".join(top)
    missing = [s for s in case.expect.contains if s not in joined]
    leaked = [s for s in case.expect.not_contains if s in joined]
    broke_abstain = case.expect.empty and bool(top)
    duplicated = case.expect.distinct and len(set(top)) < len(top)
    return CaseResult(
        suite=case.suite,
        case=case.case,
        passed=not missing and not leaked and not broke_abstain and not duplicated,
        results=top,
        missing=missing,
        leaked=leaked,
        broke_abstain=broke_abstain,
        checks_recall=bool(case.expect.contains),
        checks_leak=bool(case.expect.not_contains),
        checks_abstain=case.expect.empty,
        detail="duplicated results" if duplicated else "",
    )


@dataclass
class SuiteReport:
    suite: str
    total: int
    passed: int
    recall: float | None  # contains 가 있는 사례 중 전부 찾은 비율
    leak_rate: float | None  # not_contains 가 있는 사례 중 하나라도 샌 비율
    abstain_rate: float | None  # empty 기대 사례 중 실제로 비어 있던 비율
    mean_score: float | None = None  # score 가 있는 사례들의 평균


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ratio(hits: int, total: int) -> float | None:
    return None if total == 0 else hits / total


def summarize(results: list[CaseResult]) -> dict[str, SuiteReport]:
    by_suite: dict[str, list[CaseResult]] = {}
    for r in results:
        by_suite.setdefault(r.suite, []).append(r)

    reports: dict[str, SuiteReport] = {}
    for suite, rs in by_suite.items():
        with_contains = [r for r in rs if r.checks_recall]
        with_not = [r for r in rs if r.checks_leak]
        with_empty = [r for r in rs if r.checks_abstain]
        reports[suite] = SuiteReport(
            suite=suite,
            total=len(rs),
            passed=sum(r.passed for r in rs),
            recall=_ratio(sum(not r.missing for r in with_contains), len(with_contains)),
            leak_rate=_ratio(sum(bool(r.leaked) for r in with_not), len(with_not)),
            abstain_rate=_ratio(sum(not r.broke_abstain for r in with_empty), len(with_empty)),
            mean_score=_mean([r.score for r in rs if r.score is not None]),
        )
    return reports
