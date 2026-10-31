"""[memory] "그거", "아까 그 방법" 같은 상대 지칭을 찾아 그것이 가리키는 직전 대화를 꺼내는 순수 함수."""

import re

from jarvis.model_layer.model_types import Message

# 대명사는 낱말 앞부분으로 본다(그거, 그걸, 그게, 그건). "그 방식", "이 계획" 처럼 명사 앞의 관형사는
# 띄어 쓴 한 글자 낱말일 때만 본다. 붙여 쓴 "그" 는 그래서, 그런데 같은 접속사에도 들어 있다
DEICTIC = re.compile(
    r"(그거|그걸|그게|그건|그것|이거|이걸|이게|이건|이것|저거|저걸|저게|저건|저것|아까|방금|거기|그때|위에서|앞에서)"
    r"|(?<!\S)(그|이|저)(?=\s)"
    r"|\b(it|that|this|those|them)\b",
    re.IGNORECASE,
)
# 이보다 짧은 발화("계속", "다시 해줘")는 지칭이 없어도 혼자 뜻이 서지 않는다
SHORT_UTTERANCE_CHARS = 8
QUERY_CHARS = 200  # 회상 질의에 넣는 현재 발화 길이
CONTEXT_CHARS = 300  # 직전 대화에서 덧붙이는 길이(발화마다)


def has_deixis(text: str) -> bool:
    return DEICTIC.search(text) is not None


def text_of(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(getattr(b, "text", "") for b in message.content)


def recent_exchange(messages: list[Message], max_chars: int = CONTEXT_CHARS) -> str:
    """마지막 user 발화와 그 뒤 assistant 답의 본문. 도구 결과는 건너뛴다. 없으면 빈 문자열."""
    picked: list[str] = []
    for msg in reversed(messages):
        if msg.role == "tool_result":
            continue
        text = text_of(msg).strip()
        if not text:
            continue
        picked.append(text[:max_chars])
        if msg.role == "user":
            break
    return "\n".join(reversed(picked))


def retrieval_query(messages: list[Message]) -> str:
    """회상 질의. 마지막 user 발화가 지칭을 담거나 너무 짧으면 그 앞의 주고받음을 덧붙인다.

    메인 모델은 최근 창을 그대로 보므로 지칭을 스스로 푼다. 여기서 푸는 것은 장기 기억을 찾을 단서뿐이다.
    """
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role != "user":
            continue
        current = text_of(messages[i])[:QUERY_CHARS]
        if has_deixis(current) or len(current.strip()) < SHORT_UTTERANCE_CHARS:
            before = recent_exchange(messages[:i])
            return f"{before}\n{current}" if before else current
        return current
    return ""
