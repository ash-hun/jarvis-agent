"""[memory] 회상된 증거로 답을 만들고(LLM 1회) 정답과 맞는지 판정한다(LLM 1회, 비싸서 --judge 일 때만)."""

from jarvis.memory.eval.benchmark import BenchmarkQuestion, Judge
from jarvis.model_layer.types import LLMContext, ModelConfig, StreamOptions, UserMessage

ANSWER_PROMPT = """\
아래는 과거 대화에서 떠올린 기억이다. 이것만 근거로 질문에 짧게 답하라. 근거가 없으면 "모름" 이라고 답하라.

[기억]
{evidence}

[질문]
{question}
"""

JUDGE_PROMPT = """\
질문과 정답, 그리고 모델의 답이 있다. 모델의 답이 정답과 같은 뜻이면 yes, 아니면 no 로만 답하라.
정답이 비어 있거나 "모름" 류이고 모델도 모른다고 했으면 yes 다.

질문: {question}
정답: {answer}
모델의 답: {predicted}
"""


def llm_judge(model: ModelConfig) -> Judge:
    async def judge(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
        from jarvis.model_layer.stream import stream_to_message

        evidence = "\n".join(f"- {r}" for r in retrieved) or "- (없음)"
        answer_ctx = LLMContext(
            messages=[UserMessage(content=ANSWER_PROMPT.format(evidence=evidence, question=question.question))],
            tools=None,
        )
        predicted = (await stream_to_message(model, answer_ctx, StreamOptions())).text().strip()
        judge_ctx = LLMContext(
            messages=[UserMessage(content=JUDGE_PROMPT.format(
                question=question.question, answer=question.answer or "(없음)", predicted=predicted
            ))],
            tools=None,
        )
        verdict = (await stream_to_message(model, judge_ctx, StreamOptions())).text().strip().lower()
        return predicted, verdict.startswith("y")

    return judge


def contains_judge() -> Judge:
    """정답 문자열이 회상된 증거 안에 그대로 있는지. LLM 없이 쓰는 거친 근사."""

    async def judge(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
        gold = question.answer.strip().lower()
        joined = "\n".join(retrieved).lower()
        return joined[:200], bool(gold) and gold in joined

    return judge
