"""memory_eval 기능의 정답 판정: 기권은 판정 모델이 아니라 코드가 가린다."""

from jarvis.memory.eval.judge import LETTERS, abstained, llm_judge, picked, shuffled_choices, expects_abstention
from jarvis.model_layer.model_types import AssistantMessage, ModelConfig, TextContent
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


async def test_llm_judge_answers_with_model_and_grades_with_judge_model(monkeypatch):
    calls: list[str] = []

    async def fake_stream(model, ctx, options):  # type: ignore[no-untyped-def]
        calls.append(model.model)
        return AssistantMessage(content=[TextContent(text="yes" if model.model == "grader" else "서울")])

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)
    judge = llm_judge(ModelConfig(provider="openai", model="answerer"), ModelConfig(provider="openai", model="grader"))

    predicted, correct = await judge(BenchmarkQuestion("q1", "t", "수도?", "서울", []), ["- 서울에 산다"])

    assert (predicted, correct) == ("서울", True)
    assert calls == ["answerer", "grader"]


async def test_llm_judge_without_judge_model_grades_with_the_answer_model(monkeypatch):
    calls: list[str] = []

    async def fake_stream(model, ctx, options):  # type: ignore[no-untyped-def]
        calls.append(model.model)
        return AssistantMessage(content=[TextContent(text="no")])

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)

    await llm_judge(ModelConfig(provider="openai", model="solo"))(BenchmarkQuestion("q1", "t", "수도?", "서울", []), [])

    assert calls == ["solo", "solo"]
