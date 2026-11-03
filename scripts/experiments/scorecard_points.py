"""[scripts] 스코어카드 꼭짓점 점수, Wilson 구간, 토큰 비용과 예산 판정을 계산하는 순수 함수."""

import math
from typing import Any

Z95 = 1.96


def wilson(rate: float, n: int) -> tuple[float, float]:
    """비율 rate(0~1)와 표본 n 의 Wilson 95% 구간. n 이 0 이면 (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    p = min(max(rate, 0.0), 1.0)
    denom = 1 + Z95**2 / n
    center = (p + Z95**2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def balanced(recall: float, false_alarm: float) -> float:
    """Proactivity 꼭짓점의 원래 지표: must recall 과 (1 − must_not 오경보율)의 평균(0~1)."""
    return (recall + (1 - false_alarm)) / 2


def vertex_entry(raw: float, n: int, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """원래 지표(0~1)를 꼭짓점 기록으로. 점수와 구간은 0~100 이다."""
    lo, hi = wilson(raw, n)
    return {
        "score": round(raw * 100, 1),
        "raw": round(raw, 4),
        "n": n,
        "ci95": [round(lo * 100, 1), round(hi * 100, 1)],
        "detail": detail or {},
    }


def cost_usd(usage: dict[str, int], price: dict[str, float]) -> float:
    """토큰 사용량과 100만 토큰당 단가로 비용. 캐시 읽기와 쓰기 단가가 없으면 입력 단가를 쓴다."""
    per = 1_000_000
    return (
        usage.get("input", 0) * price["input"]
        + usage.get("output", 0) * price["output"]
        + usage.get("cache_read", 0) * price.get("cache_read", price["input"])
        + usage.get("cache_write", 0) * price.get("cache_write", price["input"])
    ) / per


def estimate_usd(reference: dict[str, int], price: dict[str, float], margin: float) -> float:
    """다른 모델로 잰 사용량을 이 단가로 옮긴 견적. 캐시 할인 없이 계산하고 margin 을 곱한다(보수적)."""
    flat = {"input": reference.get("input", 0) + reference.get("cache_read", 0) + reference.get("cache_write", 0),
            "output": reference.get("output", 0)}
    return cost_usd(flat, price) * margin


def fits_budget(spent: float, estimate: float, cap: float) -> bool:
    """이미 쓴 비용에 이 꼭짓점 견적을 더해도 상한 안이면 돌린다."""
    return spent + estimate <= cap


def kappa(a: list[bool], b: list[bool]) -> float | None:
    """두 판정자의 Cohen's kappa. 우연히 맞을 확률을 뺀 일치도. 문항이 없거나 둘 다 한쪽으로만 판정하면 None."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    return None if chance == 1 else round((observed - chance) / (1 - chance), 3)


def compare_verdicts(rows: list[dict[str, Any]], judged: list[int], regraded: list[bool]) -> dict[str, Any]:
    """원래 판정과 새 판정의 정답률, 일치율, kappa, 뒤집힌 수. 코드가 채점한 문항은 두 쪽이 같다."""
    new = [bool(r["correct"]) for r in rows]
    for i, verdict in zip(judged, regraded, strict=True):
        new[i] = verdict
    before = [bool(rows[i]["correct"]) for i in judged]
    n = len(rows)
    return {
        "original": vertex_entry(sum(bool(r["correct"]) for r in rows) / n, n),
        "regraded": vertex_entry(sum(new) / n, n),
        "llm_judged": len(judged),
        "agreement": round(sum(a == b for a, b in zip(before, regraded, strict=True)) / len(judged), 3)
        if judged else None,
        "kappa": kappa(before, regraded),
        "yes_to_no": sum(a and not b for a, b in zip(before, regraded, strict=True)),
        "no_to_yes": sum(b and not a for a, b in zip(before, regraded, strict=True)),
    }
