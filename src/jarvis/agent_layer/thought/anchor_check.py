"""[agent_layer] 먼저 건넬 말이 근거 항목(앵커)의 숫자, 이름, 핵심 낱말을 하나라도 담았는지 관대하게 본다."""

import re

TAG = re.compile(r"^\s*(\[[^\]]{1,24}\]\s*)+")
NUMBER = re.compile(r"\d[\d,.:]*")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_\-#./]{2,}")
HANGUL = re.compile(r"[가-힣]{2,}")
# 길게 붙은 조사부터 뗀다("잔액으로" → "잔액")
JOSA = ("에서는", "으로는", "에게서", "까지는", "에서", "으로", "에게", "까지", "부터", "보다", "처럼", "이랑",
        "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "로", "만")
# 어느 알림에나 들어가 근거가 되지 못하는 낱말
STOPWORDS = frozenset({
    "오늘", "내일", "지금", "예정", "안내", "알림", "일정", "확인", "있습니다", "되었습니다", "합니다", "했습니다",
    "사용자", "님이", "주세요", "하세요", "가능", "관련", "요청", "the", "and", "for", "from", "with",
})


def anchor_terms(anchor: str) -> list[str]:
    """앵커에서 숫자(쉼표 없이), 영문 낱말(소문자), 한글 낱말(조사 뗌)을 뽑는다. 출처 꼬리표는 뺀다. 순수 함수."""
    body = TAG.sub("", anchor)
    numbers = [n.replace(",", "").rstrip(".:") for n in NUMBER.findall(body)]
    latin = [w.lower() for w in LATIN.findall(body)]
    hangul = [_strip_josa(w) for w in HANGUL.findall(body)]
    terms = [t for t in numbers + latin + hangul if len(t) >= 2]
    return [t for t in dict.fromkeys(terms) if t not in STOPWORDS]


def anchor_present(anchor: str, utterance: str) -> bool:
    """말이 앵커 낱말을 하나라도 담았나. 띄어쓰기와 쉼표는 무시하고, 세 글자 넘는 한글 낱말은 앞 두 글자로도 맞춘다.

    앵커에서 뽑을 낱말이 없으면 막지 않는다(참). 순수 함수.
    """
    terms = anchor_terms(anchor)
    if not terms:
        return True
    said = re.sub(r"[\s,]", "", utterance).lower()
    for term in terms:
        if term in said or _hour(term) in said:
            return True
        if HANGUL.fullmatch(term) and len(term) >= 3 and term[:2] not in STOPWORDS and term[:2] in said:
            return True
    return False


def _hour(term: str) -> str:
    """"09:30" 은 말로 "9시" 라고 할 수 있다. 시각이 아니면 맞지 않을 빈 표식."""
    match = re.fullmatch(r"(\d{1,2}):\d{2}", term)
    return f"{int(match.group(1))}시" if match else "\0"


def _strip_josa(word: str) -> str:
    for suffix in JOSA:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            return word[: -len(suffix)]
    return word
