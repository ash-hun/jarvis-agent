"""[memory] 정답 턴(has_answer)이 턴 일화로 구성된 뒤에도 정답을 담는지 세어 구성 단계 손실을 재는 순수 함수."""

from dataclasses import dataclass, field

from jarvis.memory.eval.benchmark import BenchmarkQuestion, exchanges
from jarvis.memory.memory_service import TURN_CHARS, answer_parts
from jarvis.memory.retrieval.scoring import relevance

# 정답 낱말의 이 비율 이상이 글에 나오면 정답을 담았다고 본다. LLM 없이 세려는 근사다
HOLDS = 0.5


@dataclass
class TurnLoss:
    """정답을 원문에 담은 정답 턴 중 구성한 일화 글에도 정답이 남은 비율. 역할별로 따로 센다."""

    evidence: dict[str, int] = field(default_factory=dict)  # 역할별 정답 턴 수
    holding: dict[str, int] = field(default_factory=dict)  # 원문에 정답 낱말이 있는 정답 턴
    kept: dict[str, int] = field(default_factory=dict)  # 그중 일화 글에도 남은 것
    long: dict[str, int] = field(default_factory=dict)  # 원문이 1,000자를 넘는 정답 턴

    def rates(self) -> dict[str, dict[str, float | int]]:
        out: dict[str, dict[str, float | int]] = {}
        for role in sorted(self.evidence):
            holding = self.holding.get(role, 0)
            out[role] = {"evidence": self.evidence[role], "holding": holding, "kept": self.kept.get(role, 0),
                         "long": self.long.get(role, 0),
                         "preserved": round(self.kept.get(role, 0) / holding, 4) if holding else 1.0}
        holding = sum(self.holding.values())
        out["all"] = {"evidence": sum(self.evidence.values()), "holding": holding, "kept": sum(self.kept.values()),
                      "long": sum(self.long.values()),
                      "preserved": round(sum(self.kept.values()) / holding, 4) if holding else 1.0}
        return out


def holds(answer: str, text: str) -> bool:
    return bool(answer.strip()) and relevance(answer, text) >= HOLDS


def measure_turn_loss(questions: list[BenchmarkQuestion], max_parts: int) -> TurnLoss:
    """정답 턴을 record_turn 이 남기는 글자로 줄이고(답은 max_parts 개 조각까지) 정답이 남는지 본다."""
    loss = TurnLoss()
    for q in questions:
        for session in q.sessions:
            for _, user, answer in exchanges(session):
                for turn in (user, answer):
                    if turn is None or turn.turn_id not in q.evidence_turn_ids:
                        continue
                    role = turn.role
                    loss.evidence[role] = loss.evidence.get(role, 0) + 1
                    loss.long[role] = loss.long.get(role, 0) + (len(turn.text) > 1000)
                    if not holds(q.answer, turn.text):
                        continue
                    loss.holding[role] = loss.holding.get(role, 0) + 1
                    loss.kept[role] = loss.kept.get(role, 0) + holds(q.answer, stored_text(turn.text, role, max_parts))
    return loss


def stored_text(text: str, role: str, max_parts: int) -> str:
    """턴 일화(와 조각 일화)에 남는 그 역할의 글. 발화는 TURN_CHARS 까지, 답은 TURN_CHARS 와 조각들이다."""
    if role == "user":
        return text[:TURN_CHARS]
    return "\n".join([text[:TURN_CHARS], *answer_parts(text, max_parts)])
