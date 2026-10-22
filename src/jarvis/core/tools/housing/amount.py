"""[core] '1억 5천', '6000만', '150,000,000' 같은 한국어 금액을 원 단위 정수로 읽는 함수."""

import re

UNITS = {"억": 100_000_000, "만": 10_000, "천": 1_000}
_TOKEN = re.compile(r"(\d+(?:\.\d+)?)\s*(억|천만|백만|만|천)?")
_PLAIN = re.compile(r"\d+(?:\.\d+)?")
# 금액 뒤에 붙는 말. '3억 안쪽', '200만원 이하', '약 1억 5천 정도'
_TAIL = re.compile(r"(?:원)?(?:안쪽|이하|이내|까지|정도|쯤|내외|가량|미만)$")


def parse_won(value: object) -> int:
    """원 단위 금액. 읽을 수 없으면 ValueError."""
    # ponytail: 단위 없는 '천'('1억 5천', '5천')은 천만으로 본다(주택 금액 관례), 천 원이면 '5천원' 처럼 원을 붙인다
    if isinstance(value, bool):
        raise ValueError(f"금액이 아니다: {value}")
    if isinstance(value, int | float):
        return round(value)
    text = _TAIL.sub("", str(value or "").strip().replace(",", "").replace(" ", "").removeprefix("약"))
    if not text:
        raise ValueError("금액이 비었다")
    text = text.removesuffix("원") if not text.endswith("천원") else text
    if _PLAIN.fullmatch(text):
        return round(float(text))
    total = 0.0
    pos = 0
    for match in _TOKEN.finditer(text):
        if match.start() != pos:
            break
        number, unit = float(match.group(1)), match.group(2)
        if unit is None:
            # '1억 2000' 의 꼬리 숫자는 만 원 단위다
            total += number * (UNITS["만"] if total else 1)
        elif unit == "천":
            total += number * (1_000 if text[match.end():] == "원" else 10_000_000)
        elif unit == "천만":
            total += number * 10_000_000
        elif unit == "백만":
            total += number * 1_000_000
        else:
            total += number * UNITS[unit]
        pos = match.end()
    rest = text[pos:]
    if pos == 0 or rest not in ("", "원"):
        raise ValueError(f"금액을 읽을 수 없다: {value}")
    return round(total)
