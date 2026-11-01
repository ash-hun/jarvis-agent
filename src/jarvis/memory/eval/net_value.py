"""[memory] 같은 질문의 RAG 기준선 판정과 비교군 판정을 맞대어 memory benefit, tax, net 을 세는 순수 함수."""

from dataclasses import dataclass

from jarvis.memory.eval.benchmark import BenchmarkReport

# Memory Tax(He et al. 2026) 의 질문 단위 분해. 기준선이 틀리고 비교군이 맞으면 benefit,
# 기준선이 맞고 비교군이 틀리면 tax 다. net = benefit - tax 는 두 정답률의 차이와 같다.


@dataclass(frozen=True)
class NetValue:
    n: int  # 두 쪽 모두 판정된 질문 수
    benefit: int
    tax: int

    @property
    def net(self) -> int:
        return self.benefit - self.tax

    def rates(self) -> dict[str, float | int]:
        n = self.n or 1
        return {"n": self.n, "benefit": self.benefit, "tax": self.tax, "net": self.net,
                "benefit_rate": round(self.benefit / n, 4), "tax_rate": round(self.tax / n, 4),
                "net_rate": round(self.net / n, 4)}


def net_value(baseline: BenchmarkReport, arm: BenchmarkReport) -> NetValue:
    """question_id 로 맞댄다. 어느 한쪽이라도 판정이 없는 질문은 뺀다."""
    base = {r.question_id: r.correct for r in baseline.results if r.correct is not None}
    benefit = tax = n = 0
    for r in arm.results:
        if r.correct is None or r.question_id not in base:
            continue
        n += 1
        benefit += r.correct and not base[r.question_id]
        tax += base[r.question_id] and not r.correct
    return NetValue(n=n, benefit=benefit, tax=tax)
