"""[core] LH 공고문 PDF 를 받아 임대조건 표의 주택형별 임대보증금과 월임대료를 읽는 함수."""

import io
import re
import asyncio
from pypdf import PdfReader
from dataclasses import dataclass
from collections.abc import Callable

from jarvis.core.tools.housing.fetch import FetchBytes

FILE_URL = "https://apply.lh.or.kr/lhapply/lhFile.do"
# 임대조건 표는 공고문 앞쪽에 있다. 뒤쪽(자격, 서류 안내)까지 읽으면 느리기만 하다
MAX_PAGES = 15
# 공고문이 아닌 첨부(홍보물, 양식)
_NOT_NOTICE = re.compile(r"팸플릿|팜플렛|리플릿|별첨|붙임|서식|양식|안내문|QnA", re.IGNORECASE)
_NUMBER = r"\d{1,3}(?:,\d{3})+|\d+"
# 기본 임대조건 한 행: 보증금 계, 계약금, 잔금, 월임대료. (+), (-) 전환 행은 숫자가 셋이라 걸리지 않는다
_ROW_RE = re.compile(rf"(?<![\w,.+\-−)(])({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})(?![\d,.])")
_UNIT_RE = re.compile(r"\b(\d{2,3}[A-Z]{1,2}\d?)\b")
_SECTION = "임대조건"


@dataclass(frozen=True)
class RentTerm:
    unit: str  # 주택형과 공급대상. 예: 21A 청년(소득有)
    deposit: int  # 원
    rent: int  # 원


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
    """임대조건 절의 기본 행들. 계 = 계약금 + 잔금 인 네 숫자만 행으로 본다(다른 표의 숫자를 잘못 잡지 않게).

    보증금 머리에 '(천원)' 이 있으면 1,000 을 곱한다. 월임대료는 원 단위다.
    """
    start = text.find(_SECTION)
    if start < 0:
        return []
    section = text[start:]
    # 다음 큰 절(예: '3. 신청자격')에서 끊는다
    end = re.search(r"\n\s*\d+\.\s*(?:신청자격|입주자\s*선정|공급일정|신청방법)", section)
    section = section[: end.start()] if end else section
    thousand = "보증금(천원)" in section.replace(" ", "")
    terms: list[RentTerm] = []
    unit = ""
    for line in section.splitlines():
        units = _UNIT_RE.findall(line)
        if units:
            unit = units[0]
        match = next((m for m in _ROW_RE.finditer(line) if _balanced(m)), None)
        if match is None:
            continue
        total, _, _, rent = (int(g.replace(",", "")) for g in match.groups())
        label = line[: match.start()].strip()
        label = re.sub(r"^\(?[+\-−]\)?", "", label).strip()
        if unit and label.startswith(unit):
            label = label[len(unit):].strip()
        # 같은 줄의 면적, 호수 같은 숫자 칸은 이름에서 뺀다
        label = re.sub(r"\s+", " ", re.sub(r"(?<!\S)[\d.,]+(?!\S)", " ", label)).strip()
        name = " ".join(part for part in (unit, label if label != unit else "") if part).strip() or "주택형 미상"
        terms.append(RentTerm(name, total * 1000 if thousand else total, rent))
    return terms


def _balanced(match: re.Match[str]) -> bool:
    """계 = 계약금 + 잔금(반올림 오차 허용). 면적, 호수 같은 다른 숫자 묶음을 거른다."""
    total, first, rest, _ = (int(g.replace(",", "")) for g in match.groups())
    return total > 0 and abs(first + rest - total) <= max(2, total // 1000)


async def notice_rent_terms(
    fetch_file: FetchBytes, file_id: str, referer: str, read_pdf: Callable[[bytes], str] = pdf_text
) -> list[RentTerm]:
    data = await fetch_file(FILE_URL, {"fileid": file_id}, referer)
    # PDF 풀기는 CPU 일이라 이벤트 루프를 막지 않게 스레드에서 한다
    text = await asyncio.to_thread(read_pdf, data)
    return rent_terms(text)
