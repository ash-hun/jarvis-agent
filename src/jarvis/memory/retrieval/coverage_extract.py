"""[memory] 질문에서 기억으로 찾아야 할 대상(사람, 장소, 물건, 일)을 뽑는 LLM 경계."""

import json
from collections.abc import Awaitable, Callable

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamOptions, UserMessage

# 대상이 많으면 재검색이 노출 자리를 다 가져간다. 질문 하나에 이만큼만 본다
MAX_ENTITIES = 4
MAX_ENTITY_CHARS = 40

# 질문 → 대상 이름들. 실패하면 빈 목록(호출자는 1차 회상만 쓴다)
EntityExtractor = Callable[[str], Awaitable[list[str]]]

PROMPT = """\
아래 질문에 답하려면 과거 대화 기억에서 찾아야 하는 대상을 뽑아라.
대상은 사람, 장소, 물건, 활동, 사건처럼 기억 속 사실을 가리키는 짧은 명사구다.
질문에 쓰인 말 그대로 쓰고, 날짜, 숫자, "나", "너", "사용자" 는 빼라. 최대 {limit}개.
JSON 배열로만 답하라. 예: ["dentist appointment", "Emma"]. 없으면 [].

[질문]
{question}
"""


def parse_entities(raw: str) -> list[str]:
    """JSON 배열에서 대상 이름만 남긴다. 같은 이름은 한 번, 너무 긴 것과 빈 것은 버린다. 순수 함수."""
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end < start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[str] = []
    for value in data if isinstance(data, list) else []:
        name = str(value).strip() if isinstance(value, str) else ""
        if name and len(name) <= MAX_ENTITY_CHARS and name.lower() not in {n.lower() for n in out}:
            out.append(name)
    return out[:MAX_ENTITIES]


def llm_entity_extractor(model: ModelConfig) -> EntityExtractor:
    async def extract(question: str) -> list[str]:
        from jarvis.model_layer.stream import stream_to_message

        prompt = PROMPT.format(limit=MAX_ENTITIES, question=question)
        result = await stream_to_message(model, LLMContext(messages=[UserMessage(content=prompt)]), StreamOptions())
        if result.error_message is not None:
            return []
        return parse_entities(result.text())

    return extract
