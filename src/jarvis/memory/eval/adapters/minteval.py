"""[memory] MINT-Eval(Lee et al. 2026) 네 영역의 시간순 맥락과 질문을 BenchmarkQuestion 으로 바꾼다."""

import json
from typing import Any
from pathlib import Path

from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkSession, BenchmarkTurn

# 원본 https://huggingface.co/datasets/dinobby/MINTEval (parquet 를 split 별 jsonl 로 바꿔 둔다, 레포 밖)
# 영역: state_tracking(bAbI 문장), multi_turn_dialogue(대화 세션), wiki_revisions(문서 판), github_commits(커밋 스냅숏)
# 질문 유형: simple, counting, history, ordering, multi-hop. 질문 metadata 의 n_steps_back 은 위치 힌트일 뿐
# 정답 맥락 라벨이 아니어서 증거 재현율은 내지 않는다.
DIALOGUE = "multi_turn_dialogue"
SESSION_CONTEXTS = 20  # 대화가 아닌 영역은 맥락을 이만큼씩 묶어 가짜 세션으로 둔다. 턴 비교군의 공고화 단위다
_SPEAKERS = ("user:", "assistant:")


def parse_minteval(records: list[dict[str, Any]]) -> list[BenchmarkQuestion]:
    questions: list[BenchmarkQuestion] = []
    for rec in records:
        split = str(rec.get("split", "unknown"))
        corpus = f"{split}:{rec.get('id', len(questions))}"
        contexts = list(rec.get("contexts", []) or [])
        sessions = _dialogue_sessions(corpus, contexts) if split == DIALOGUE else _grouped_sessions(corpus, contexts)
        for index, q in enumerate(rec.get("questions", []) or []):
            questions.append(BenchmarkQuestion(
                question_id=f"{corpus}:{index}",
                question_type=str(q.get("question_type", "unknown")),
                question=str(q.get("question", "")),
                answer=str(q.get("answer", "")),
                sessions=sessions,
                corpus_id=corpus,
            ))
    return questions


def load_minteval(path: Path) -> list[BenchmarkQuestion]:
    """path 는 split jsonl 하나 또는 그것들이 든 디렉토리. 레코드에 split 칸이 없으면 파일 이름을 쓴다."""
    path = Path(path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    records: list[dict[str, Any]] = []
    for file in files:
        for line in file.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                rec = json.loads(line)
                rec.setdefault("split", file.stem)
                records.append(rec)
    return parse_minteval(records)


def _grouped_sessions(corpus: str, contexts: list[dict[str, Any]]) -> list[BenchmarkSession]:
    sessions: list[BenchmarkSession] = []
    for start in range(0, len(contexts), SESSION_CONTEXTS):
        group = contexts[start : start + SESSION_CONTEXTS]
        turns = [
            BenchmarkTurn(role="user", text=str(c.get("content", "")), turn_id=f"{corpus}#{start + i}")
            for i, c in enumerate(group)
        ]
        date = str(group[0].get("timestamp", "") or "")
        sessions.append(BenchmarkSession(session_id=f"{corpus}:s{start // SESSION_CONTEXTS}", date=date, turns=turns))
    return sessions


def _dialogue_sessions(corpus: str, contexts: list[dict[str, Any]]) -> list[BenchmarkSession]:
    """맥락 하나가 대화 세션 하나다. "user:", "assistant:" 줄에서 턴을 나누고 앞의 장면 설명은 첫 턴에 붙인다."""
    sessions: list[BenchmarkSession] = []
    for index, context in enumerate(contexts):
        turns: list[BenchmarkTurn] = []
        preface: list[str] = []
        for line in str(context.get("content", "")).split("\n"):
            speaker = next((s for s in _SPEAKERS if line.lower().startswith(s)), None)
            if speaker is not None:
                text = line[len(speaker):].strip()
                if preface and not turns:
                    text = "\n".join([*preface, text])
                turns.append(BenchmarkTurn(role=speaker[:-1], text=text, turn_id=f"{corpus}#{index}.{len(turns)}"))
            elif turns:
                turns[-1].text += "\n" + line
            else:
                preface.append(line)
        if not turns and preface:
            turns.append(BenchmarkTurn(role="user", text="\n".join(preface), turn_id=f"{corpus}#{index}.0"))
        sessions.append(BenchmarkSession(
            session_id=f"{corpus}:s{index}", date=str(context.get("timestamp", "") or ""), turns=turns
        ))
    return sessions
