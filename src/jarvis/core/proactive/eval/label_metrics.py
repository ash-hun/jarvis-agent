"""[core] 3단 라벨(must, can, must_not)로 recall, 오경보, AUC 를 순수 함수로 계산한다."""

from collections.abc import Sequence

from jarvis.core.proactive.eval.eval_schema import CaseLabel


def recall_must(labels: Sequence[CaseLabel], spoke: Sequence[bool]) -> float | None:
    """must 사례 중 말한 비율. must 가 없으면 None."""
    hits = [s for label, s in zip(labels, spoke, strict=True) if label == "must"]
    return sum(hits) / len(hits) if hits else None


def false_alarm_must_not(labels: Sequence[CaseLabel], spoke: Sequence[bool]) -> float | None:
    """must_not 사례 중 말한 비율. can 은 어느 쪽이든 괜찮아 세지 않는다. must_not 이 없으면 None."""
    hits = [s for label, s in zip(labels, spoke, strict=True) if label == "must_not"]
    return sum(hits) / len(hits) if hits else None


def auc_must(labels: Sequence[CaseLabel], scores: Sequence[float | None]) -> float | None:
    """must 를 양성, must_not 을 음성으로 둔 AUC(같은 점수는 반). 점수가 없는 사례(사고 실패)는 0 으로 본다.

    양성이나 음성이 하나도 없으면 None.
    """
    pos = [s or 0.0 for label, s in zip(labels, scores, strict=True) if label == "must"]
    neg = [s or 0.0 for label, s in zip(labels, scores, strict=True) if label == "must_not"]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))
