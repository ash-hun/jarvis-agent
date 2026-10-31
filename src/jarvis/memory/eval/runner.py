"""[memory] 사례를 대상에 넣고 질의해 판정한다(사례마다 저장소를 비우므로 실행 순서에 의존하지 않는다)."""

from pathlib import Path
from typing import TYPE_CHECKING, Any
from dataclasses import asdict, dataclass

from jarvis.memory.eval.schema import EvalCase, RetentionCase, load_cases, load_retention_cases
from jarvis.memory.eval.metrics import CaseResult, SuiteReport, judge, summarize
from jarvis.memory.eval.target import EvalTarget
from jarvis.model_layer.types import Message

if TYPE_CHECKING:
    from jarvis.memory.consolidation.compaction import Summarizer
    from jarvis.memory.eval.faithfulness import FactJudge

DATASETS_DIR = Path(__file__).parent / "datasets"
STORE_SUITES = ("isolation", "semantic", "episodic", "procedural", "paraphrase")
# 계층 재설계(층별 권한, 일화 cherry-pick, 절차 정제)
REDESIGN_SUITES = ("access", "episode_filter", "consolidation")
RETENTION_SUITES = ("retention",)
FAITHFULNESS_SUITES = ("faithfulness",)
SUITES = STORE_SUITES + REDESIGN_SUITES + RETENTION_SUITES + FAITHFULNESS_SUITES


@dataclass
class EvalReport:
    cases: list[CaseResult]
    suites: dict[str, SuiteReport]
    injected_chars: int = 0  # 회상 결과 총 글자 수. 주입 토큰의 근사치
    llm_calls: int = 0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suites": {k: asdict(v) for k, v in self.suites.items()},
            "cases": [asdict(c) for c in self.cases],
            "injected_chars": self.injected_chars,
            "llm_calls": self.llm_calls,
        }


def load_suites(names: list[str]) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for name in names:
        if name in STORE_SUITES + REDESIGN_SUITES:
            cases.extend(load_cases(DATASETS_DIR / f"{name}.jsonl"))
    return cases


async def run(cases: list[EvalCase], target: EvalTarget) -> EvalReport:
    results: list[CaseResult] = []
    injected = 0
    for case in cases:
        await target.reset()
        for step in case.setup:
            await target.setup(step, case.step_scope(step))
        found = await target.probe(
            case.probe, case.scope.to_scope(), case.expect.top_k, case.probe_kind, case.filter, case.policy
        )
        injected += sum(len(s) for s in found)
        results.append(judge(case, found))
    return EvalReport(cases=results, suites=summarize(results), injected_chars=injected)


def load_retention_suites(names: list[str]) -> list[RetentionCase]:
    cases: list[RetentionCase] = []
    for name in names:
        if name in RETENTION_SUITES:
            cases.extend(load_retention_cases(DATASETS_DIR / f"{name}.jsonl"))
    return cases


async def run_retention(cases: list[RetentionCase], target: EvalTarget) -> EvalReport:
    """질문 턴 컨텍스트에 답이 있으면 통과. injected_chars 는 그 컨텍스트의 총 글자 수다."""
    results: list[CaseResult] = []
    total = 0
    for case in cases:
        context = await target.converse(case)
        chars = sum(len(_text(m)) for m in context)
        total += chars
        found = any(case.answer in _text(m) for m in context)
        results.append(CaseResult(
            suite=case.suite,
            case=case.case,
            passed=found,
            results=[f"distance={case.distance}", f"messages={len(context)}", f"context_chars={chars}"],
            missing=[] if found else [case.answer],
            checks_recall=True,
        ))
    return EvalReport(cases=results, suites=summarize(results), injected_chars=total)


def _text(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content
    return message.text() if hasattr(message, "text") else ""


async def run_faithfulness_suite(
    names: list[str], summarizer: "Summarizer | None" = None, judge: "FactJudge | None" = None
) -> EvalReport | None:
    """faithfulness 스위트. 요약기와 판정기가 없으면 오프라인 기준선(추출 요약 + 문자열 포함)."""
    from jarvis.memory.eval.faithfulness import (
        FaithfulnessCase,
        contains_fact_judge,
        extractive_summarizer,
        load_faithfulness_cases,
        run_faithfulness,
    )

    cases: list[FaithfulnessCase] = []
    for name in names:
        if name in FAITHFULNESS_SUITES:
            cases.extend(load_faithfulness_cases(DATASETS_DIR / f"{name}.jsonl"))
    if not cases:
        return None
    results = await run_faithfulness(cases, summarizer or extractive_summarizer(), judge or contains_fact_judge())
    return EvalReport(cases=results, suites=summarize(results))


def merge(*reports: EvalReport) -> EvalReport:
    cases = [c for r in reports for c in r.cases]
    return EvalReport(
        cases=cases,
        suites=summarize(cases),
        injected_chars=sum(r.injected_chars for r in reports),
        llm_calls=sum(r.llm_calls for r in reports),
    )


def format_report(report: EvalReport, verbose: bool = False) -> str:
    lines = [f"{'suite':<13}{'pass':>8}{'recall':>9}{'leak':>8}{'abstain':>9}{'score':>8}"]
    for s in report.suites.values():
        lines.append(
            f"{s.suite:<13}{f'{s.passed}/{s.total}':>8}"
            f"{_fmt(s.recall):>9}{_fmt(s.leak_rate):>8}{_fmt(s.abstain_rate):>9}{_fmt(s.mean_score):>8}"
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
