"""memory_eval 기능의 구성 손실 측정: 정답 턴이 턴 일화로 줄어도 정답을 담는지."""

from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkSession, BenchmarkTurn
from jarvis.memory.eval.turn_loss import holds, measure_turn_loss, stored_text


def _question(answer_text: str) -> BenchmarkQuestion:
    turns = [BenchmarkTurn("user", "우산 추천해줘", "s#0"), BenchmarkTurn("assistant", answer_text, "s#1", True)]
    return BenchmarkQuestion("q", "single-session-assistant", "무슨 우산?", "보라색 장우산",
                             [BenchmarkSession("s", "", turns)], {"s"}, {"s#1"})


def test_answer_beyond_the_cut_is_lost_without_parts_and_kept_with_parts():
    question = _question("가" * 1200 + "\n추천은 보라색 장우산이다.")

    before = measure_turn_loss([question], 0).rates()
    after = measure_turn_loss([question], 2).rates()

    assert before["assistant"]["preserved"] == 0.0 and before["assistant"]["long"] == 1
    assert after["all"]["preserved"] == 1.0


def test_evidence_without_the_answer_words_is_not_counted_as_holding():
    rates = measure_turn_loss([_question("다른 이야기")], 0).rates()

    assert rates["assistant"]["holding"] == 0 and rates["all"]["preserved"] == 1.0
    assert not holds("", "아무 글")


def test_stored_text_cuts_user_side_at_turn_chars():
    assert stored_text("가" * 1500, "user", 2) == "가" * 1000
