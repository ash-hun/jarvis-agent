"""memory_eval 기능의 MINT-Eval 어댑터: 대화 영역은 턴으로 나누고 나머지는 맥락을 묶으며 증거 라벨은 없다."""

import json

from jarvis.memory.eval.adapters.minteval import SESSION_CONTEXTS, load_minteval, parse_minteval

DIALOGUE = {
    "split": "multi_turn_dialogue", "id": "u1",
    "contexts": [{"content": "[scenario] homesick\nuser: hi\nassistant: hello\nstill hello\nuser: bye",
                  "timestamp": "2025-09-26T16:39:09"}],
    "questions": [{"question": "q?", "answer": "a", "question_type": "simple", "metadata": "{}"}],
}


def test_dialogue_context_becomes_a_session_of_turns_with_the_scene_on_the_first():
    (question,) = parse_minteval([DIALOGUE])

    turns = question.sessions[0].turns
    assert [t.role for t in turns] == ["user", "assistant", "user"]
    assert turns[0].text == "[scenario] homesick\nhi" and turns[1].text == "hello\nstill hello"
    assert question.evidence_turn_ids == set() and question.corpus == "multi_turn_dialogue:u1"


def test_other_domains_group_contexts_into_pseudo_sessions(tmp_path):
    rec = {"id": "s", "contexts": [{"content": f"step {i}", "timestamp": ""} for i in range(SESSION_CONTEXTS + 1)],
           "questions": [{"question": "where?", "answer": "kitchen", "question_type": "history"}]}
    (tmp_path / "state_tracking.jsonl").write_text(json.dumps(rec) + "\n\n", encoding="utf-8")

    (question,) = load_minteval(tmp_path)

    assert question.question_id == "state_tracking:s:0"
    assert [len(s.turns) for s in question.sessions] == [SESSION_CONTEXTS, 1]
    assert parse_minteval([{"split": "x", "contexts": [], "questions": []}]) == []
