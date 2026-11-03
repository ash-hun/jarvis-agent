"""[memory] 회상된 증거로 답을 만들고(LLM 1회) 정답과 맞는지 판정한다(LLM 1회, 비싸서 --judge 일 때만)."""

import re
import random

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamOptions, UserMessage
from jarvis.memory.eval.benchmark import BenchmarkQuestion, Judge

ABSTAIN = "모름"
# 정답이 "근거 없음" 인 질문 유형. LongMemEval 은 _abs 질문, LoCoMo 는 adversarial(정답 칸이 비어 있다)
ABSTAIN_TYPES = frozenset({"abstention", "adversarial"})

ANSWER_PROMPT = """\
아래는 과거 대화에서 떠올린 기억이다. 이것만 근거로 질문에 짧게 답하라. 근거가 없으면 "모름" 이라고 답하라.

[기억]
{evidence}

[질문]
{question}
"""

# 객관식(PersonaMem-v2)은 같은 답 프롬프트 뒤에 보기만 붙인다. 판정은 기호 일치로 코드가 한다(Memory Tax 부록 A.3)
CHOICES_PROMPT = """
[보기]
{options}

보기 중 하나의 기호만 답하라.
"""
LETTERS = "ABCDEFGH"
_LETTER = re.compile(r"\b([A-H])\b")

JUDGE_PROMPT = """\
질문과 정답, 그리고 모델의 답이 있다. 모델의 답이 정답과 같은 뜻이면 yes, 아니면 no 로만 답하라.

질문: {question}
정답: {answer}
모델의 답: {predicted}
"""


def llm_judge(model: ModelConfig, judge_model: ModelConfig | None = None) -> Judge:
    """model 이 답하고 judge_model(없으면 model)이 판정한다. 모델끼리 비교할 때는 판정자를 하나로 고정한다."""
    grader = judge_model or model

    async def judge(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
        from jarvis.model_layer.stream import stream_to_message

        evidence = "\n".join(f"- {r}" for r in retrieved) or "- (없음)"
        prompt = ANSWER_PROMPT.format(evidence=evidence, question=question.question)
        options = shuffled_choices(question)
        if options:
            prompt += CHOICES_PROMPT.format(options="\n".join(f"{LETTERS[i]}. {c}" for i, c in enumerate(options)))
        answer_ctx = LLMContext(messages=[UserMessage(content=prompt)], tools=None)
        predicted = (await stream_to_message(model, answer_ctx, StreamOptions())).text().strip()
        if options:
            return predicted, picked(predicted, options) == question.answer
        if abstained(predicted):
            # 판정 LLM 은 "모름" 을 정답이 있는 질문에도 맞다고 했다(raw 100문항 중 50여 건). 기권은 코드가 판정한다
            return predicted, expects_abstention(question)
        judge_ctx = LLMContext(
            messages=[UserMessage(content=JUDGE_PROMPT.format(
                question=question.question, answer=question.answer or "(없음)", predicted=predicted
            ))],
            tools=None,
        )
        verdict = (await stream_to_message(grader, judge_ctx, StreamOptions())).text().strip().lower()
        return predicted, verdict.startswith("y")

    return judge


def shuffled_choices(question: BenchmarkQuestion) -> list[str]:
    """보기 순서를 질문 id 로 섞는다. 정답이 늘 같은 자리에 있지 않고, 다시 돌려도 같은 순서다."""
    options = list(question.choices)
    random.Random(question.question_id).shuffle(options)
    return options


def picked(predicted: str, options: list[str]) -> str | None:
    """답에서 처음 나온 보기 기호의 보기. 기호가 없으면 None(틀림)."""
    match = _LETTER.search(predicted.strip().upper()[:20])
    if match is None:
        return None
    index = LETTERS.index(match.group(1))
    return options[index] if index < len(options) else None


def abstained(predicted: str) -> bool:
    return predicted.strip().startswith(ABSTAIN)


def expects_abstention(question: BenchmarkQuestion) -> bool:
    return question.question_type in ABSTAIN_TYPES or not question.answer.strip()


def contains_judge() -> Judge:
    """정답 문자열이 회상된 증거 안에 그대로 있는지. LLM 없이 쓰는 거친 근사."""

    async def judge(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
        gold = question.answer.strip().lower()
        joined = "\n".join(retrieved).lower()
        return joined[:200], bool(gold) and gold in joined

    return judge
