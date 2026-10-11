"""[memory] LongMemEval(Wu et al. 2024) 질문과 haystack 세션 묶음을 BenchmarkQuestion 으로 바꾼다."""

import json
from pathlib import Path
from typing import Any

from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkSession, BenchmarkTurn

# 원본 https://github.com/xiaowu0162/LongMemEval
# 증거는 answer_session_ids(세션 단위)와 턴의 has_answer(턴 단위) 둘 다 있다.
# 질문 유형: single-session-user, single-session-assistant, single-session-preference, temporal-reasoning,
# knowledge-update, multi-session, abstention(_abs)


def parse_longmemeval(records: list[dict[str, Any]]) -> list[BenchmarkQuestion]:
    questions: list[BenchmarkQuestion] = []
    for rec in records:
        qid = str(rec["question_id"])
        qtype = str(rec.get("question_type", "unknown"))
        if qid.endswith("_abs"):
            qtype = "abstention"
        session_ids = [str(s) for s in rec.get("haystack_session_ids", [])]
        dates = [str(d) for d in rec.get("haystack_dates", [])]
        sessions: list[BenchmarkSession] = []
        evidence_turns: set[str] = set()
        for index, turns in enumerate(rec.get("haystack_sessions", [])):
            sid = session_ids[index] if index < len(session_ids) else f"session_{index}"
            date = dates[index] if index < len(dates) else ""
            parsed: list[BenchmarkTurn] = []
            for t_index, turn in enumerate(turns):
                turn_id = f"{sid}#{t_index}"
                is_evidence = bool(turn.get("has_answer", False))
                if is_evidence:
                    evidence_turns.add(turn_id)
                parsed.append(BenchmarkTurn(role=str(turn.get("role", "user")), text=str(turn.get("content", "")),
                                            turn_id=turn_id, is_evidence=is_evidence))
            sessions.append(BenchmarkSession(session_id=sid, date=date, turns=parsed))
        questions.append(BenchmarkQuestion(
            question_id=qid,
            question_type=qtype,
            question=str(rec["question"]),
            answer=str(rec.get("answer", "")),
            sessions=sessions,
            evidence_session_ids={str(s) for s in rec.get("answer_session_ids", [])},
            evidence_turn_ids=evidence_turns,
        ))
    return questions


def load_longmemeval(path: Path) -> list[BenchmarkQuestion]:
    return parse_longmemeval(json.loads(Path(path).read_text(encoding="utf-8")))
