"""LoCoMo (Maharana et al. 2024). https://github.com/snap-research/locomo

샘플 하나가 두 화자의 긴 대화(session_N, session_N_date_time)와 qa 목록을 가진다.
qa 의 evidence 는 dia_id 목록(턴 단위). category 는 논문 기준 1 multi-hop, 2 temporal,
3 open-domain, 4 single-hop, 5 adversarial(답 없음).
"""

import json
import re
from pathlib import Path

from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkSession, BenchmarkTurn

CATEGORY = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}
_SESSION_KEY = re.compile(r"^session_(\d+)$")


def parse_locomo(samples: list[dict]) -> list[BenchmarkQuestion]:
    questions: list[BenchmarkQuestion] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id", len(questions)))
        conversation = sample.get("conversation", {})
        sessions: list[BenchmarkSession] = []
        turn_session: dict[str, str] = {}
        keys = sorted(
            (int(m.group(1)), k) for k in conversation for m in [_SESSION_KEY.match(k)] if m
        )
        for _, key in keys:
            sid = f"{sample_id}:{key}"
            date = str(conversation.get(f"{key}_date_time", ""))
            turns: list[BenchmarkTurn] = []
            for turn in conversation.get(key, []) or []:
                dia_id = str(turn.get("dia_id", f"{key}:{len(turns)}"))
                text = str(turn.get("text", ""))
                caption = turn.get("blip_caption")
                if caption:
                    text = f"{text} (사진: {caption})"
                turns.append(BenchmarkTurn(role="user", text=f"{turn.get('speaker', '')}: {text}", turn_id=dia_id))
                turn_session[dia_id] = sid
            sessions.append(BenchmarkSession(session_id=sid, date=date, turns=turns))
        for index, qa in enumerate(sample.get("qa", []) or []):
            evidence = {str(e) for e in qa.get("evidence", []) or []}
            questions.append(BenchmarkQuestion(
                question_id=f"{sample_id}:{index}",
                question_type=CATEGORY.get(int(qa.get("category", 0) or 0), "unknown"),
                question=str(qa.get("question", "")),
                answer=str(qa.get("answer", "")),
                sessions=sessions,
                evidence_session_ids={turn_session[e] for e in evidence if e in turn_session},
                evidence_turn_ids=evidence,
            ))
    return questions


def load_locomo(path: Path) -> list[BenchmarkQuestion]:
    return parse_locomo(json.loads(Path(path).read_text(encoding="utf-8")))
