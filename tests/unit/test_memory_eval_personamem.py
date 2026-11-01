"""memory_eval 기능의 PersonaMem-v2 어댑터: system 턴 제외, 가짜 세션, 증거 턴, 객관식 보기."""

import json

from jarvis.memory.eval.adapters.personamem import HISTORY_COLUMN, SESSION_MESSAGES, load_personamem, parse_personamem

LINK = "data/chat_history_128k/p7.json"
HISTORY = [{"role": "system", "content": "persona: loves spicy food"}] + [
    {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(SESSION_MESSAGES + 2)
]
ROW = {
    "persona_id": "7", HISTORY_COLUMN: LINK, "pref_type": "stereotypical_pref",
    "user_query": "{'role': 'user', 'content': 'Suggest a dinner'}",
    "correct_answer": "Spicy jollof", "incorrect_answers": '["Plain rice", "Salad", "Soup"]',
    "related_conversation_snippet": json.dumps([{"role": "user", "content": f"turn {SESSION_MESSAGES}"}]),
}


def test_parse_drops_system_turn_and_maps_snippet_to_turns_and_pseudo_sessions():
    (question,) = parse_personamem([ROW], {LINK: HISTORY})

    assert question.question == "Suggest a dinner" and question.corpus == "pm7"
    assert question.choices == ["Spicy jollof", "Plain rice", "Salad", "Soup"]
    assert [len(s.turns) for s in question.sessions] == [SESSION_MESSAGES, 2]
    assert all("persona" not in t.text for s in question.sessions for t in s.turns)
    assert question.evidence_turn_ids == {f"7#{SESSION_MESSAGES + 1}"}  # system 이 0번이라 한 칸 밀린다
    assert question.evidence_session_ids == {"pm7:s1"}


def test_rows_without_a_downloaded_history_are_skipped(tmp_path):
    csv_path = tmp_path / "text" / "benchmark.csv"
    csv_path.parent.mkdir()
    csv_path.write_text(",".join(ROW) + "\n" + ",".join(json.dumps(v) for v in ROW.values()) + "\n", encoding="utf-8")

    assert load_personamem(csv_path) == []
    (tmp_path / LINK).parent.mkdir(parents=True)
    (tmp_path / LINK).write_text(json.dumps({"chat_history": HISTORY}), encoding="utf-8")
    assert len(load_personamem(csv_path)) == 1
