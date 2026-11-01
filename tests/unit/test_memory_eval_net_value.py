"""memory_eval 기능의 순이득: RAG 대비 benefit, tax, net 을 질문 단위로 센다."""

from jarvis.memory.eval.benchmark import BenchmarkReport, QuestionResult
from jarvis.memory.eval.net_value import net_value


def _report(mode: str, correct: dict[str, bool | None]) -> BenchmarkReport:
    results = [QuestionResult(q, "t", [], None, None, correct=c) for q, c in correct.items()]
    return BenchmarkReport(name="b", mode=mode, k=5, results=results)


def test_benefit_tax_and_net_match_the_accuracy_difference():
    rag = _report("rag", {"a": True, "b": False, "c": True, "d": False})
    arm = _report("turns", {"a": True, "b": True, "c": False, "d": False})

    value = net_value(rag, arm)

    assert (value.benefit, value.tax, value.net, value.n) == (1, 1, 0, 4)
    assert value.rates()["tax_rate"] == 0.25


def test_unjudged_or_unmatched_questions_are_left_out():
    rag = _report("rag", {"a": True, "b": None})
    arm = _report("raw", {"a": False, "b": True, "z": True})

    value = net_value(rag, arm)

    assert (value.n, value.benefit, value.tax) == (1, 0, 1)
    assert net_value(rag, _report("raw", {})).rates()["net_rate"] == 0.0
