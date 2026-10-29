"""[core] SH 모집 공고를 고르고 공고문 PDF 에서 보증금과 월임대료, 분양가와 토지임대료를 읽는 함수."""

import re
import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from dataclasses import dataclass, replace

from jarvis.core.tools.housing.sh_notice import SH_BASE, BOARDS, Post, list_query, list_url, parse_detail, parse_list
from jarvis.core.tools.housing.fetch import Fetch, FetchBytes, FetchError
from jarvis.core.tools.housing.notice_pdf import pdf_text
from jarvis.core.tools.housing.sh_notice import view_url
from jarvis.core.tools.housing.lh_notice import Notice

SH_ID_PREFIX = "sh-"
SH_REGION = "서울특별시"
# 첨부 내려받기. 게시판 스크립트(innorix.config.js)의 downUrl 과 같다
FILE_URL = f"{SH_BASE}/app/com/file/innoFD.do"
# 모집 글을 고르는 게시판과 쪽 수. 2026-10-29 실측으로 열린 모집 글은 임대 첫 세 쪽, 분양 첫 쪽 안에 있었다
BOARD_PAGES = (("임대", 3), ("분양", 1))
# ponytail: 최근 RECENT_DAYS 안에 올라온 모집 글 MAX_NOTICES 건만 본다, 오래 열려 있는 공고를 놓치면 쪽을 늘린다
RECENT_DAYS = 90
MAX_NOTICES = 10
# 분양 공고문은 앞 50쪽 남짓이 팸플릿이고 가격표가 그 뒤에 있다(고덕강일 3단지 136쪽 중 51~82쪽)
PDF_PAGES = 120
# 게시판과 첨부 서버에 동시에 거는 요청 수
CONCURRENCY = 4
# 모집 공고가 아닌 글(계약 안내, 서류 제출 안내, 당첨 발표)
_NOT_RECRUIT = re.compile(r"안내|발표|결과|당첨|경쟁률")
# 공고문이 아닌 첨부. LH 와 달리 SH 는 공고문 이름에 '붙임' 을 달기도 해서 따로 거른다
_NOT_NOTICE_FILE = re.compile(r"신청서|서식|양식|동의서|위임장|안내문|평면도|기준|별지")
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_DATE_RE = re.compile(r"(20\d{2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})")
# 보증금 머리 줄에서 이만큼 아래까지만 금액 행을 찾는다. 소득 기준표처럼 멀리 있는 숫자 줄을 행으로 읽지 않는다
ROWS_BELOW_HEADER = 40
DEPOSIT_RANGE = (1_000_000, 2_000_000_000)
RENT_RANGE = (10_000, 5_000_000)
# 보증금이 월임대료의 이 배보다 작으면 금액 행이 아니다(소득 기준표 '2,669,354 4,106,389')
MIN_DEPOSIT_TO_RENT = 10
# 동 호 주택형 주택타입 주택가격 계약금 잔금. 예: '301 201 059.0000B 59B 371,544 37,154 334,390'
_SALE_ROW_RE = re.compile(
    r"^\s*\d+\s+\d+\s+0*(\d{2,3})\.\d{4}([A-Z]\d?)\s+\S+\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", re.MULTILINE
)
# 토지임대료 표의 행. 예: '49 426,000 전용 49㎡ 전체 주택형에 동일 적용'
_LAND_ROW_RE = re.compile(r"^\s*(\d{2,3})\s+(\d{1,3}(?:,\d{3})+)\b", re.MULTILINE)


@dataclass(frozen=True)
class ShUnit:
    unit: str  # 호수나 주택형. 예: 604, 59B
    price: int  # 보증금이나 분양가(원)
    rent: int  # 월임대료나 월 토지임대료(원)
    sale: bool
    low: int = 0  # 분양이면 층별 최저가(원)


def sh_id(seq: str) -> str:
    return f"{SH_ID_PREFIX}{seq}"


def is_sh(nid: str) -> bool:
    return nid.startswith(SH_ID_PREFIX)


def sh_url(notice: Notice) -> str:
    """SH 공고 글 주소. 분양 글은 분양 게시판, 나머지는 임대 게시판으로 연다."""
    board = BOARDS["분양" if notice.kind.endswith("분양") else "임대"]
    return view_url(board, notice.id.removeprefix(SH_ID_PREFIX))


def recruiting(posts: list[Post], category: str, today: date) -> list[Notice]:
    """게시판 글 중 최근에 올라온 모집 공고. 상태 칸이 없어 제목 말로 고른다. 순수 함수."""
    since = (today - timedelta(days=RECENT_DAYS)).isoformat()
    return [
        Notice(sh_id(p.seq), f"SH {category}", p.title, SH_REGION, p.registered, "", "공고중")
        for p in posts
        if p.status == "모집/접수" and "모집" in p.title and not _NOT_RECRUIT.search(p.title) and p.registered >= since
    ]


def close_date(content: str) -> str:
    """게시글 본문의 접수 기간 중 가장 늦은 날(YYYY.MM.DD). 접수 줄이 없으면 빈 글. 순수 함수.

    게시판에 마감 칸이 없다. 본문의 '■ 접수일' 단락은 다음 '■' 까지다.
    """
    start = content.find("접수")
    if start < 0:
        return ""
    end = content.find("■", start)
    dates = [(int(y), int(m), int(d)) for y, m, d in _DATE_RE.findall(content[start:end if end > 0 else None])]
    return "{}.{:02d}.{:02d}".format(*max(dates)) if dates else ""


def pick_sh_pdf(files: list[dict[str, str]]) -> dict[str, str] | None:
    """첨부 중 공고문 PDF. 이름에 '공고' 가 든 것을 먼저 고른다."""
    pdfs = [f for f in files if f["name"].lower().endswith(".pdf") and not _NOT_NOTICE_FILE.search(f["name"])]
    return next((f for f in pdfs if "공고" in f["name"]), pdfs[0] if pdfs else None)


def sh_pdf_text(data: bytes) -> str:
    return pdf_text(data, PDF_PAGES)


def rent_units(text: str) -> list[ShUnit]:
    """임대 공고문의 (보증금, 월임대료) 행. 보증금 머리 줄 아래 ROWS_BELOW_HEADER 줄 안의 금액 쌍만 본다. 순수 함수.

    SH 공고문은 단지마다 표 모양이 달라(호수별, 소득 구간별 두 쌍, 주택명별) 줄 안의 금액 쌍으로 읽는다.
    소득 구간이 둘이면 뒤 쌍(소득이 높은 구간, 비싼 쪽)을 쓴다. 비싼 쪽으로 봐야 모자람을 놓치지 않는다.
    """
    units: list[ShUnit] = []
    seen: set[tuple[int, int]] = set()
    below = ROWS_BELOW_HEADER + 1
    for line in text.splitlines():
        below = 0 if "보증금" in line else below + 1
        if below > ROWS_BELOW_HEADER:
            continue
        found = [(m.start(), int(m.group().replace(",", ""))) for m in _AMOUNT_RE.finditer(line)]
        pairs = [
            (at, deposit, rent)
            for (at, deposit), (_, rent) in zip(found, found[1:], strict=False)
            if DEPOSIT_RANGE[0] <= deposit <= DEPOSIT_RANGE[1] and RENT_RANGE[0] <= rent <= RENT_RANGE[1]
            and deposit >= MIN_DEPOSIT_TO_RENT * rent
        ]
        if not pairs:
            continue
        first_at, deposit, rent = pairs[0][0], *pairs[-1][1:]
        if (deposit, rent) in seen:
            continue
        seen.add((deposit, rent))
        label = " ".join(line[:first_at].replace("원", " ").split())[:40] or f"보증금 {deposit:,}원"
        units.append(ShUnit(label, deposit, rent, False))
    return units


def sale_units(text: str) -> list[ShUnit]:
    """분양 공고문의 동호별 가격표를 주택형별 최저가, 최고가로 묶고 토지임대료를 붙인다. 순수 함수.

    가격(주택가격) = 계약금 + 잔금 인 행만 읽는다. 단위는 표 머리의 '주택가격(천원)' 을 따른다.
    """
    scale = 1000 if "주택가격(천원)" in text.replace(" ", "") else 1
    prices: dict[tuple[int, str], list[int]] = {}
    for area, letter, price, first, rest in _SALE_ROW_RE.findall(text):
        values = [int(v.replace(",", "")) for v in (price, first, rest)]
        if abs(values[0] - values[1] - values[2]) <= 1:
            prices.setdefault((int(area), letter), []).append(values[0] * scale)
    land = land_rents(text)
    return [
        ShUnit(f"{area}{letter}", max(values), land.get(area, 0), True, min(values))
        for (area, letter), values in prices.items()
    ]


def land_rents(text: str) -> dict[int, int]:
    """토지임대부 분양의 전용면적별 월 토지임대료. 표가 없으면 빈 dict. 순수 함수."""
    head = re.search(r"토지임대료\s*\(\s*원\s*/\s*월\s*\)", text)
    if head is None:
        return {}
    block = text[head.end():head.end() + 400]
    return {int(area): int(rent.replace(",", "")) for area, rent in _LAND_ROW_RE.findall(block)}


async def collect(
    fetch: Fetch, fetch_file: FetchBytes, read: Callable[[bytes], str], today: date
) -> list[tuple[Notice, list[ShUnit]]]:
    """열린 SH 모집 공고와 그 공고문에서 읽은 금액. 목록을 못 받으면 FetchError, 한 공고의 실패는 빈 금액으로 남긴다."""
    gate = asyncio.Semaphore(CONCURRENCY)
    wanted = [(category, page) for category, pages in BOARD_PAGES for page in range(1, pages + 1)]

    async def listing(category: str, page: int) -> list[Notice]:
        board = BOARDS[category]
        async with gate:
            parsed = parse_list(await fetch(list_url(board), list_query(board, "", "제목", page)))
        if parsed is None:
            raise FetchError("SH 게시판이 목록 표를 주지 않았다")
        return recruiting(parsed[1], category, today)

    found: dict[str, Notice] = {}
    # 쪽 순서대로 모은다. 같은 글이 두 쪽에 걸려도 앞 쪽 것 하나다
    for notices in await asyncio.gather(*(listing(c, p) for c, p in wanted)):
        for notice in notices:
            found.setdefault(notice.id, notice)

    async def one(notice: Notice) -> tuple[Notice, list[ShUnit]]:
        async with gate:
            return await _amounts(fetch, fetch_file, read, notice)

    return list(await asyncio.gather(*(one(n) for n in list(found.values())[:MAX_NOTICES])))


async def _amounts(
    fetch: Fetch, fetch_file: FetchBytes, read: Callable[[bytes], str], notice: Notice
) -> tuple[Notice, list[ShUnit]]:
    """공고 글의 접수 마감과 공고문 금액. 못 받거나 못 읽으면 금액 없이 돌려준다(한 공고로 추천을 멈추지 않는다)."""
    url = sh_url(notice)
    base, _, query = url.partition("?")
    try:
        detail = parse_detail(await fetch(base, dict(p.split("=", 1) for p in query.split("&"))))
        if detail is None:
            return notice, []
        notice = replace(notice, closes=close_date(detail["content"]))
        file = pick_sh_pdf(detail["attachments"])
        if file is None:
            return notice, []
        data = await fetch_file(FILE_URL, dict(p.split("=", 1) for p in file["download"].split("&")), url)
        # PDF 풀기는 CPU 일이라 이벤트 루프를 막지 않게 스레드에서 한다(분양 공고문 120쪽에 수 초)
        text = await asyncio.to_thread(read, data)
    except Exception:  # FetchError, 깨진 PDF(pypdf 의 여러 예외)
        return notice, []
    return notice, sale_units(text) if notice.kind.endswith("분양") else rent_units(text)

