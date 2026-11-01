"""[memory] PersonaMem-v2(Jiang et al. 2025) 객관식 질문과 128k 대화 이력을 BenchmarkQuestion 으로 바꾼다."""

import ast
import csv
import json
from typing import Any
from pathlib import Path

from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkSession, BenchmarkTurn

# 원본 https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2 의 benchmark/text/benchmark.csv(5,000 질문, 200명)
# 이력은 세션 없이 한 줄로 이어진 user/assistant 턴이다. 맨 앞 system 턴은 페르소나 전체를 담아 정답이 새므로 뺀다.
# 증거는 related_conversation_snippet 이 이력의 어느 턴과 글자 그대로 같은지로 찾는다.
SESSION_MESSAGES = 40  # 세션이 없어 이만큼씩 묶어 가짜 세션으로 둔다. 턴 비교군의 공고화 단위다
HISTORY_COLUMN = "chat_history_128k_link"  # Memory Tax 는 128k 이력을 썼다


def read_rows(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(1 << 30)
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_personamem(rows: list[dict[str, str]], histories: dict[str, list[dict[str, Any]]]) -> list[BenchmarkQuestion]:
    """histories 는 이력 링크 → 턴 목록. 이력이 없는 행은 건너뛴다(필요한 이력만 받아 둔다)."""
    questions: list[BenchmarkQuestion] = []
    for index, row in enumerate(rows):
        history = histories.get(row.get(HISTORY_COLUMN, ""))
        if history is None:
            continue
        persona = str(row.get("persona_id", ""))
        sessions, turn_session = _sessions(persona, history)
        by_content: dict[str, list[str]] = {}
        for t_index, turn in enumerate(history):
            by_content.setdefault(str(turn.get("content", "")), []).append(f"{persona}#{t_index}")
        evidence = {
            turn_id
            for turn in _literal_list(row.get("related_conversation_snippet", ""))
            if isinstance(turn, dict)
            for turn_id in by_content.get(str(turn.get("content", "")), [])
            if turn_id in turn_session
        }
        correct = str(row.get("correct_answer", ""))
        query = _literal(row.get("user_query", ""))
        questions.append(BenchmarkQuestion(
            question_id=f"pm{persona}:{index}",
            question_type=str(row.get("pref_type", "unknown")),
            question=str(query.get("content", "")) if isinstance(query, dict) else str(query),
            answer=correct,
            sessions=sessions,
            evidence_session_ids={turn_session[t] for t in evidence},
            evidence_turn_ids=evidence,
            corpus_id=f"pm{persona}",
            choices=[correct, *(str(a) for a in _literal_list(row.get("incorrect_answers", "")))],
        ))
    return questions


def load_personamem(path: Path) -> list[BenchmarkQuestion]:
    """path 는 benchmark/text/benchmark.csv(또는 그 사본). 이력 링크는 데이터셋 루트(path 의 두 단계 위) 기준이다."""
    rows = read_rows(path)
    root = Path(path).resolve().parent.parent
    histories: dict[str, list[dict[str, Any]]] = {}
    for link in {r.get(HISTORY_COLUMN, "") for r in rows}:
        file = root / link
        if link and file.is_file():
            histories[link] = list(json.loads(file.read_text(encoding="utf-8")).get("chat_history", []))
    return parse_personamem(rows, histories)


def _sessions(persona: str, history: list[dict[str, Any]]) -> tuple[list[BenchmarkSession], dict[str, str]]:
    sessions: list[BenchmarkSession] = []
    turn_session: dict[str, str] = {}
    turns = [(i, t) for i, t in enumerate(history) if t.get("role") in ("user", "assistant")]
    for start in range(0, len(turns), SESSION_MESSAGES):
        sid = f"pm{persona}:s{start // SESSION_MESSAGES}"
        parsed = [
            BenchmarkTurn(role=str(t["role"]), text=str(t.get("content", "")), turn_id=f"{persona}#{i}")
            for i, t in turns[start : start + SESSION_MESSAGES]
        ]
        for turn in parsed:
            turn_session[turn.turn_id] = sid
        sessions.append(BenchmarkSession(session_id=sid, date="", turns=parsed))
    return sessions, turn_session


def _literal(text: str) -> Any:
    """열 값이 JSON 이기도 하고 파이썬 repr 이기도 하다."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text


def _literal_list(text: str) -> list[Any]:
    value = _literal(text)
    return [v for v in value if isinstance(v, (dict, str))] if isinstance(value, list) else []
