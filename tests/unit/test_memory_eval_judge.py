"""memory_eval 기능의 정답 판정: 기권은 판정 모델이 아니라 코드가 가린다."""

from jarvis.memory.eval.judge import LETTERS, abstained, expects_abstention, picked, shuffled_choices
from tests.fixtures.memory_eval_helpers import LONGMEMEVAL_SAMPLE
from jarvis.memory.eval.benchmark import BenchmarkQuestion
from jarvis.memory.eval.adapters import load_longmemeval


def test_abstention_is_judged_by_code_not_by_the_judge_model():
    answerable, unanswerable = load_longmemeval(LONGMEMEVAL_SAMPLE)

    assert abstained("모름") and abstained(" 모름.") and not abstained("Business Administration")
    assert not expects_abstention(answerable) and expects_abstention(unanswerable)


def test_choices_are_shuffled_by_question_id_and_letters_pick_them():
    question = BenchmarkQuestion("pm1:3", "t", "dinner?", "Spicy", [], choices=["Spicy", "Rice", "Salad", "Soup"])

    options = shuffled_choices(question)

    assert sorted(options) == sorted(question.choices) and options == shuffled_choices(question)
    assert picked(f"{LETTERS[options.index('Spicy')]}. Spicy", options) == "Spicy"
    assert picked("모름", options) is None
