"""[core] LH 공고문 PDF 를 받아 임대조건 표(보증금, 월임대료)와 분양가 표(주택가격)를 읽는 함수."""

import io
import re
import asyncio
from pypdf import PdfReader
from collections.abc import Callable
from dataclasses import dataclass, replace

from jarvis.core.tools.housing.fetch import FetchBytes

FILE_URL = "https://apply.lh.or.kr/lhapply/lhFile.do"
# 임대조건 표는 공고문 앞쪽에 있다. 뒤쪽(자격, 서류 안내)까지 읽으면 느리기만 하다
MAX_PAGES = 15
# 공고문이 아닌 첨부(홍보물, 양식)
_NOT_NOTICE = re.compile(r"팸플릿|팜플렛|리플릿|별첨|붙임|서식|양식|안내문|QnA", re.IGNORECASE)
_NUMBER = r"\d{1,3}(?:,\d{3})+|\d+"
_INT_RE = re.compile(rf"(?:{_NUMBER})")
# 최대전환 행의 머리. '(+)', '(-)' 뒤에 전환 한도, 전환 뒤 보증금, 전환 뒤 월임대료가 온다
_CONV_RE = re.compile(r"\(\s*([+\-−])\s*\)")
_FIXED_RE = re.compile(rf"({_NUMBER})\s*\(\s*정액\s*\)")
_UNIT_RE = re.compile(r"^(\d{2,3}[A-Z]{1,2}\d?)\b")
# 주택형 코드에 글자가 없는 공고(예: '26 대학생')는 공급대상 낱말 바로 앞의 숫자를 형별로 본다
_GROUP_RE = re.compile(r"^(?:대학생|청년|고령자|신혼|주거급여|수급자|한부모|일반|산업단지|장애|국가유공)")
# 표 머리와 구조, 난방 칸의 낱말. 공급대상 이름에 섞이지 않게 뺀다
_NOISE = {
    "기타공용", "주차장", "벽식", "라멘", "지역", "개별", "중앙", "난방", "구조", "및", "/", "-", "■", "•",
    "계", "계약금", "잔금",
}
_SECTION = "임대조건"
# 분양가 표의 주택형: '59A', '55A-1', '84AH', '059.8900A'(앞 0 과 소수 면적을 떼고 59A 로 쓴다)
_SALE_UNIT_RE = re.compile(r"^0?(\d{2,3})(?:\.\d+)?([A-Z]{1,3}(?:-\d+)?)$")
# 주택가격으로 보는 범위(원). 옵션, 발코니, 면적, 합계 숫자를 가격으로 읽지 않는다
SALE_PRICE_MIN = 100_000_000
SALE_PRICE_MAX = 3_000_000_000
_UNIT_MARK_RE = re.compile(r"[\[(]?\s*단위\s*:?\s*(천원|원)")
# 주택형 코드나 앞 가격 행에서 이만큼 낱말(층, 기본형, 쪽 번호)이 지나면 다른 표다
SALE_ROW_GAP = 8
SALE_HEADER_CHARS = 2000
SALE_MAX_PARTS = 6
# 보증금(천원 단위면 천원)과 월임대료의 최솟값. 호수, 면적, 거주기간 같은 작은 숫자 묶음을 행으로 읽지 않는다
MIN_AMOUNT = 1_000


@dataclass(frozen=True)
class SaleTerm:
    unit: str  # 주택형. 예: 59A
    low: int  # 층별 최저 주택가격(원)
    high: int  # 층별 최고 주택가격(원)
    loan: int = 0  # 공고문의 융자금(주택도시기금) 칸. 없으면 0


@dataclass(frozen=True)
class RentTerm:
    unit: str  # 주택형과 공급대상. 예: 21A 청년(소득有)
    deposit: int  # 원
    rent: int  # 원
    more: tuple[int, int] | None = None  # 보증금 최대 증액 전환 뒤 (보증금, 월임대료)
    less: tuple[int, int] | None = None  # 보증금 최대 감액 전환 뒤 (보증금, 월임대료)


def pick_notice_pdf(files: list[tuple[str, str]]) -> str | None:
    """첨부 (파일 id, 이름) 중 공고문 PDF 의 id."""
    for file_id, name in files:
        if name.lower().endswith(".pdf") and not _NOT_NOTICE.search(name):
            return file_id
    return None


def pdf_text(data: bytes, max_pages: int = MAX_PAGES) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])


def rent_terms(text: str) -> list[RentTerm]:
    """'임대조건' 이 나오는 자리마다 표를 읽어 처음으로 행이 나온 곳의 결과. 앞쪽 안내문의 '임대조건' 은 건너뛴다."""
    pos = text.find(_SECTION)
    while pos >= 0:
        section = text[pos:]
        # 다음 큰 절(예: '3. 신청자격')에서 끊는다
        end = re.search(r"\n\s*\d+\.\s*(?:신청자격|입주자\s*선정|공급일정|신청방법)", section)
        terms = _table(section[: end.start()] if end else section)
        if terms:
            return terms
        pos = text.find(_SECTION, pos + len(_SECTION))
    return []


def _table(section: str) -> list[RentTerm]:
    """표를 낱말 흐름으로 읽는다. PDF 가 한 행을 여러 줄로 쪼개도(계약금 '500 (정액)') 행이 이어진다.

    기본 행은 보증금 계, 계약금, 잔금, 월임대료(계 = 계약금 + 잔금).
    계약금이 정액이라 칸이 합쳐진 행은 계, 잔금, 월임대료.
    보증금 머리에 '(천원)' 이 있으면 1,000 을 곱한다. 월임대료는 원 단위다.
    """
    scale = 1000 if "보증금(천원)" in section.replace(" ", "") else 1
    fixed_match = _FIXED_RE.search(section)
    fixed = _int(fixed_match.group(1)) if fixed_match else None
    tokens = re.sub(r"\(\s*정액\s*\)", " ", section).split()
    tokens = [part for token in tokens for part in _split_conv(token)]
    terms: list[RentTerm] = []
    context: list[str] = []
    unit = ""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if "임대료" in token:  # 표 머리(페이지마다 되풀이된다)
            context = []
            i += 1
            continue
        conv = _CONV_RE.fullmatch(token)
        if conv:
            numbers = _ints(tokens[i + 1:], 3)
            if terms and numbers is not None:
                pair = (numbers[1] * scale, numbers[2])
                last = terms[-1]
                # 부호보다 보증금이 늘었는지로 가른다. 부호가 잘못 찍힌 공고문이 있다
                terms[-1] = replace(last, more=pair) if pair[0] > last.deposit else replace(last, less=pair)
                # 전환 행 앞의 낱말은 앞 행의 나머지 칸(면적, 거주기간, 구조)이다
                context = []
                i += 4
            else:
                i += 1
            continue
        row = _row(tokens, i, fixed)
        if row is None:
            context.append(token)
            i += 1
            continue
        (total, rent), width = row
        name, unit = _label(context, unit)
        terms.append(RentTerm(name, total * scale, rent))
        context = []
        i += width
    return terms


def _split_conv(token: str) -> list[str]:
    """전환 머리가 숫자에 붙어 있으면('(+)5,000') 떼어 낸다. 머리 앞에 붙은 값('20(-)10,000' 의 20)은 앞 행의
    마지막 칸(거주기간 등)이라 버린다."""
    parts = re.split(r"(\(\s*[+\-−]\s*\))", token)
    if len(parts) == 1:
        return [token]
    return [part for part in parts[1:] if part]


def _row(tokens: list[str], i: int, fixed: int | None) -> tuple[tuple[int, int], int] | None:
    """i 에서 시작하는 기본 행의 (보증금 계, 월임대료) 와 차지한 낱말 수."""
    four = _ints(tokens[i:], 4)
    if four is not None:
        total, first, rest, rent = four
        if total >= MIN_AMOUNT and rent >= MIN_AMOUNT and abs(first + rest - total) <= max(2, total // 1000):
            return (total, rent), 4
    three = _ints(tokens[i:], 3)
    if fixed is not None and three is not None:
        total, rest, rent = three
        if total >= MIN_AMOUNT and rent >= MIN_AMOUNT and total - rest == fixed:
            return (total, rent), 3
    return None


def _label(context: list[str], unit: str) -> tuple[str, str]:
    """행 앞 낱말들로 만든 (이름, 이어 쓸 주택형). 주택형이 없으면 앞 행의 것을 잇는다."""
    words: list[str] = []
    for index, word in enumerate(context):
        code = _UNIT_RE.match(word)
        follows = context[index + 1] if index + 1 < len(context) else ""
        if code:
            unit = code.group(1)
            rest = word[code.end():].strip()
            if rest:
                words.append(rest)
        elif re.fullmatch(r"\d{2,3}", word) and _GROUP_RE.match(follows):
            unit = word
        elif re.sub(r"\(.*\)$", "", word) not in _NOISE and not re.fullmatch(r"[\d.,()/\-−+%]+", word):
            words.append(word)
    label = re.sub(r"·\s+", "·", " ".join(words)).strip()
    name = " ".join(part for part in (unit, label) if part) or "주택형 미상"
    return name, unit


def sale_terms(text: str) -> list[SaleTerm]:
    """분양가 표의 주택형별 주택가격. 가격 뒤 납부 칸(계약금, 중도금, 잔금, 융자금, 할부금)의 합이 가격인 행만 읽는다.

    같은 주택형의 층별 행은 최저가와 최고가로 묶는다. 금액 단위는 가장 가까운 '[단위 : 천원]' 표시를 따른다.
    옵션, 발코니 표도 합이 맞아서, 주택형 코드 바로 뒤이거나 앞 가격 행에 이어지는 행만 가격으로 본다.
    계약금이 정액이면 둘째 층부터 계약금 칸이 비어 있어(병합 칸) 앞 행의 계약금을 더해 맞춘다.
    """
    start = text.find("주택가격")
    if start < 0:
        start = text.find("분양가격")
    if start < 0:
        return []
    before = text[:start]
    scale = 1000 if before.rfind("천원") > before.rfind("단위 : 원") and "천원" in before else 1
    # PDF 가 칸을 붙여 뽑기도 한다('55,000,000마이너스옵션')
    tokens = re.sub(r"(\d)([가-힣])", r"\1 \2", text[start:]).split()
    loan_column = "융자금" in text[start:start + SALE_HEADER_CHARS]
    prices: dict[str, list[int]] = {}
    loans: dict[str, int] = {}
    unit = "주택형 미상"
    unit_at = 0  # 마지막으로 주택형 코드나 가격 행이 끝난 자리
    deposit: int | None = None  # 앞 가격 행의 계약금
    i = 0
    while i < len(tokens):
        marker = _UNIT_MARK_RE.match(" ".join(tokens[i:i + 3]))
        if marker:
            scale = 1000 if marker.group(1) == "천원" else 1
        code = _SALE_UNIT_RE.match(tokens[i])
        if code:
            unit = f"{int(code.group(1))}{code.group(2)}"
            unit_at = i
            i += 1
            continue
        row = _sale_row(tokens, i, scale, deposit) if i - unit_at <= SALE_ROW_GAP else None
        if row is None:
            i += 1
            continue
        price, parts, merged = row
        prices.setdefault(unit, []).append(price)
        if loan_column and len(parts) >= 2:
            loans[unit] = parts[-1]
        if not merged:
            deposit = parts[0] // scale
        i += 1 + len(parts)
        unit_at = i
    return [
        SaleTerm(unit, min(values), max(values), loans.get(unit, 0)) for unit, values in prices.items()
    ]


def _sale_row(tokens: list[str], i: int, scale: int, deposit: int | None) -> tuple[int, list[int], bool] | None:
    """i 의 가격(원), 합이 가격이 되는 가장 짧은 뒤 숫자 묶음(원), 앞 행 계약금을 더해 맞췄는지."""
    value = _int(tokens[i])
    if value is None or not SALE_PRICE_MIN <= value * scale <= SALE_PRICE_MAX:
        return None
    for count in range(2, SALE_MAX_PARTS + 1):
        parts = _ints(tokens[i + 1:], count)
        if parts is None:
            return None
        if not all(0 < p < value for p in parts):
            continue
        tolerance = max(2, value // 10_000)
        if abs(sum(parts) - value) <= tolerance:
            return value * scale, [p * scale for p in parts], False
        if deposit is not None and abs(sum(parts) + deposit - value) <= tolerance:
            return value * scale, [p * scale for p in parts], True
    return None


def _int(token: str) -> int | None:
    return int(token.replace(",", "")) if _INT_RE.fullmatch(token) else None


def _ints(tokens: list[str], count: int) -> list[int] | None:
    """앞 count 개 낱말이 모두 정수면 그 값들."""
    values = [_int(t) for t in tokens[:count]]
    return values if len(values) == count and None not in values else None  # type: ignore[return-value]


async def notice_text(
    fetch_file: FetchBytes, file_id: str, referer: str, read_pdf: Callable[[bytes], str] = pdf_text
) -> str:
    data = await fetch_file(FILE_URL, {"fileid": file_id}, referer)
    # PDF 풀기는 CPU 일이라 이벤트 루프를 막지 않게 스레드에서 한다
    return await asyncio.to_thread(read_pdf, data)
