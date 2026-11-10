"""[memory] 사용자 발화가 기억된 사실을 바로잡는 말인지 가리는 순수 규칙."""

import re

# 정정은 드물고 놓치면 공고화 때 늦게 고쳐질 뿐이다. 넓게 잡아도 비용은 그 턴의 추출 한 번이다
_CORRECTION = re.compile(
    r"^\s*(아니|아냐|아뇨|no\b|nope\b)|아니야|아니라|아니고|틀렸|틀린|잘못 (알|기억|말)|정정|바뀌었|바꿨|"
    r"이제는|더 이상|그게 아니|\bactually\b|that'?s (wrong|not right|incorrect)|\bnot anymore\b|\bno longer\b|"
    r"\bi meant\b|\bcorrection\b",
    re.IGNORECASE,
)


def is_correction(text: str) -> bool:
    """사실을 바로잡거나 바뀐 사실을 알리는 말인가. 순수 함수."""
    return bool(_CORRECTION.search(text))
