"""[core] LH 청약플러스 공개 공고 게시판을 지역, 상태, 유형, 키워드로 조회하고 KST 기준 마감을 붙이는 lh_notice 도구."""

import re
import asyncio
from typing import Any
from dataclasses import dataclass
from collections.abc import Callable
from datetime import date, timedelta

from jarvis.core.tools.housing.markup import deadline_label, lines_of, parse_date, table_rows, text_of
from jarvis.core.tools.housing.fetch import Fetch, FetchError, fetch_html, kst_today
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool

TOOL_NAME = "lh_notice"
LH_BASE = "https://apply.lh.or.kr"
LIST_URL = f"{LH_BASE}/lhapply/apply/wt/wrtanc/selectWrtancList.do"
DETAIL_URL = f"{LH_BASE}/lhapply/apply/wt/wrtanc/selectWrtancInfo.do"
# 공공데이터포털 LH API 는 서비스키가 필요해 키 없이 열리는 청약플러스 게시판을 읽는다
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
# 게시판은 15, 30, 50, 100 건만 받는다. 그 밖의 값은 오류 페이지를 준다
PAGE_SIZES = (15, 30, 50, 100)
# ponytail: 전부 볼 때 100건씩 MAX_PAGES 쪽까지만 넘긴다, 조건에 맞는 공고가 그보다 많으면 지역이나 상태로 좁혀 부른다
MAX_PAGES = 5
# 게시판 기본 기간(최근 2개월)보다 넓게 본다. 수시모집 공고는 연초에 올라와 연말까지 열려 있다
DEFAULT_PERIOD_DAYS = 365
DETAIL_TEXT_LIMIT = 1200
# 주택형 표에서 버튼 칸. 머리와 값의 칸 수를 맞추려고 함께 뺀다
UNIT_NOISE = ("상세보기", "주택형안내", "")


@dataclass(frozen=True)
class Category:
    """게시판 메뉴(mi)와 유형 코드. srch 는 '전체' 선택지 값, upp 는 대분류 코드."""

    menu: str
    srch: str
    upp: str


CATEGORIES: dict[str, Category] = {
    "임대": Category("1026", "061339", "06"),
    "주거복지": Category("1026", "13", "13"),
    "신혼희망타운": Category("1026", "39", "39"),
    "분양": Category("1027", "053954", "05"),
    "토지": Category("1062", "01", "01"),
    "상가": Category("1069", "22", "22"),
}
# 유형을 비우면 주택 공고(임대, 분양)를 함께 본다
HOUSING = ("임대", "분양")
# 세부 유형 → (분류, 대분류/세부 코드). 게시판 선택지 값 그대로
SUBTYPES: dict[str, tuple[str, str]] = {
    "통합공공임대": ("임대", "06/48"),
    "국민임대": ("임대", "06/07"),
    "공공임대": ("임대", "06/08"),
    "영구임대": ("임대", "06/09"),
    "행복주택": ("임대", "06/10"),
    "장기전세": ("임대", "06/11"),
    "신축다세대매입임대": ("임대", "06/27"),
    "6년공공임대": ("임대", "06/52"),
    "매입임대": ("주거복지", "13/26"),
    "전세임대": ("주거복지", "13/17"),
    "집주인임대": ("주거복지", "13/36"),
    "통합공공임대(신혼희망)": ("신혼희망타운", "39/51"),
    "행복주택(신혼희망)": ("신혼희망타운", "39/42"),
    "공공분양(신혼희망)": ("분양", "39/39"),
    "분양주택": ("분양", "05/05"),
    "이익공유형분양": ("분양", "54/54"),
}
REGIONS: dict[str, str] = {
    "서울특별시": "11", "부산광역시": "26", "대구광역시": "27", "인천광역시": "28", "대전광역시": "30",
    "울산광역시": "31", "세종특별자치시": "36110", "경기도": "41", "강원특별자치도": "51", "충청북도": "43",
    "충청남도": "44", "전북특별자치도": "52", "전남광주통합특별시": "12", "경상북도": "47", "경상남도": "48",
    "제주특별자치도": "50",
}
# 줄임말로 부르는 지역. 앞 글자로 못 고르는 것만 둔다
REGION_ALIASES = {"충북": "충청북도", "충남": "충청남도", "전북": "전북특별자치도", "전남": "전남광주통합특별시",
                  "광주": "전남광주통합특별시", "경북": "경상북도", "경남": "경상남도"}
# 상세 링크의 메뉴. 신혼희망 공공분양(39/39)은 분양 메뉴, 나머지 39 와 13 은 임대 메뉴에 있다
MENU_BY_UPP = {"05": "1027", "54": "1027", "01": "1062", "22": "1069"}
# '공고중'은 게시판에서 접수중, 정정공고중까지 함께 보여준다
STATUSES = ("공고중", "접수중", "접수마감", "정정공고중", "상담요청")
ORDERS = ("최신순", "마감순")
# 실서버에서 작은 모델이 결과 정리를 빠뜨리거나 금액을 손으로 계산해 틀렸다. 결과 끝에 다음 할 일을 적는다
LIST_HINT = "답할 때 공고마다 공고명, 지역, 마감 표시(대괄호 안 값 그대로), 링크를 적는다. 상세는 id 로 부른다."
DETAIL_HINT = "대출 상환액은 직접 계산하지 말고 housing_loan 에 notice_id={nid} 와 unit(주택형)을 넣어 부른다."

TOOL_DESCRIPTION = (
    "한국토지주택공사(LH) 청약플러스(apply.lh.or.kr)의 임대, 분양, 주거복지(매입/전세임대), 신혼희망타운, 토지, 상가"
    " 공고를 조회한다."
    " 목록은 지역, 상태, 공고유형, 세부유형, 키워드로 거르고 KST 오늘 기준 마감(D-n, 오늘 마감, 마감됨)을 붙인다."
    " id 를 주면 그 공고의 상세(공급일정, 주택형별 세대수와 보증금, 임대료 또는 분양가, 공고문 파일명)를 본다."
    " SH(서울주택도시공사) 공고는 sh_notice 를 쓴다."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "상세를 볼 공고 id. 목록 결과의 id 그대로. 주면 다른 조건은 무시"},
        "category": {"type": "string", "enum": list(CATEGORIES), "description": "공고유형. 비우면 임대와 분양"},
        "subtype": {"type": "string", "enum": list(SUBTYPES), "description": "세부유형. 주면 category 는 무시"},
        "region": {"type": "string", "description": "지역. 예: 서울, 경기도, 부산광역시. 비우면 전국"},
        "status": {
            "type": "string",
            "enum": list(STATUSES),
            "description": "공고 상태. '공고중'은 접수중 포함. 현재 올라온, 진행 중인 공고를 물으면 공고중",
        },
        "keyword": {"type": "string", "description": "공고명에 들어간 말. 예: 청년, 행복주택"},
        "closing_within_days": {"type": "integer", "description": "오늘부터 n일 안에 마감하는 공고만"},
        "limit": {"type": "integer", "description": f"돌려줄 공고 수(기본 {DEFAULT_LIMIT}, 최대 {MAX_LIMIT})"},
        "order": {"type": "string", "enum": list(ORDERS), "description": "기본 최신순. 마감순은 마감 임박부터"},
    },
}

_TOTAL_RE = re.compile(r"bbs_total[^>]*>\s*전체\s*<strong>\s*([\d,]+)")
_TBODY_RE = re.compile(r"<div class=\"bbs_ListA\">[\s\S]*?<tbody>([\s\S]*?)</tbody>")
_ROW_RE = re.compile(r"<tr>([\s\S]*?)</tr>")
_LINK_RE = re.compile(r'data-id1="(\d+)" data-id2="(\d+)" data-id3="(\d+)" data-id4="(\d*)" class="wrtancInfoBtn"')
_TITLE_RE = re.compile(r'class="wrtancInfoBtn">\s*(?:<!--[\s\S]*?-->)?\s*<span>([\s\S]*?)(?:<em\b|</span>)')
_TD_RE = re.compile(r"<td\b[^>]*>([\s\S]*?)</td>")
_TABLE_RE = re.compile(r"<table\b[\s\S]*?</table>")
_ID_RE = re.compile(r"^(\d{4,20})-(\d{1,4})-(\d{1,4})-(\d{0,4})$")


@dataclass(frozen=True)
class Notice:
    id: str
    kind: str
    title: str
    region: str
    posted: str
    closes: str
    status: str


@dataclass(frozen=True)
class Query:
    """게시판에 보낼 조건. 같은 Query 는 같은 요청이다."""

    category: str
    code: str  # "06/10" 처럼 대분류/세부. 비면 분류 전체
    region: str
    status: str
    keyword: str
    closing_within_days: int | None
    limit: int
    order: str = "최신순"
    all_pages: bool = False  # 첫 쪽만이 아니라 조건에 맞는 공고 전부

    @property
    def exhaustive(self) -> bool:
        """마감순은 최신 한 쪽만 보면 일찍 올라온 임박 공고를 놓친다."""
        return self.all_pages or self.order == "마감순"


def notice_id(pan_id: str, system: str, upp: str, ais: str) -> str:
    """상세 조회에 필요한 네 값을 한 문자열로. 모델이 그대로 옮겨 적기 쉽다."""
    return f"{pan_id}-{system}-{upp}-{ais}"


def _menu(upp: str, ais: str) -> str:
    return "1027" if (upp, ais) == ("39", "39") else MENU_BY_UPP.get(upp, CATEGORIES["임대"].menu)


def is_sale(nid: str) -> bool:
    """분양(매각 포함) 공고인가. 게시판이 분양 메뉴(1027)로 여는 공고다."""
    match = _ID_RE.match(nid)
    return match is not None and _menu(match.group(3), match.group(4)) == "1027"


def detail_url(nid: str) -> str:
    pan_id, system, upp, ais = _ID_RE.match(nid).groups()  # type: ignore[union-attr]  # 부른 쪽이 검사했다
    menu = _menu(upp, ais)
    return f"{DETAIL_URL}?panId={pan_id}&ccrCnntSysDsCd={system}&uppAisTpCd={upp}&aisTpCd={ais}&mi={menu}"


def resolve_region(name: str) -> str | None:
    """'서울', '경기', '충북' 같은 말을 게시판 지역 코드로. 모르면 None, 비우면 전국('')."""
    name = name.strip()
    if not name or name == "전국":
        return ""
    name = REGION_ALIASES.get(name, name)
    for full, code in REGIONS.items():
        if full.startswith(name) or name.startswith(full):
            return code
    return None


def build_queries(params: dict[str, Any]) -> tuple[list[Query], str | None]:
    """도구 인자를 게시판 조건으로. 틀린 값이면 (빈 목록, 이유)."""
    subtype = str(params.get("subtype") or "").strip()
    category = str(params.get("category") or "").strip()
    code = ""
    if subtype:
        if subtype not in SUBTYPES:
            return [], f"모르는 세부유형: {subtype} (가능: {', '.join(SUBTYPES)})"
        category, code = SUBTYPES[subtype]
    if category and category not in CATEGORIES:
        return [], f"모르는 공고유형: {category} (가능: {', '.join(CATEGORIES)})"
    region = resolve_region(str(params.get("region") or ""))
    if region is None:
        return [], f"모르는 지역: {params.get('region')} (가능: 전국, {', '.join(REGIONS)})"
    status = str(params.get("status") or "").strip()
    if status and status not in STATUSES:
        return [], f"모르는 상태: {status} (가능: {', '.join(STATUSES)})"
    within = params.get("closing_within_days")
    try:
        closing = None if within in (None, "") else max(0, int(within))
        limit = min(MAX_LIMIT, max(1, int(params.get("limit") or DEFAULT_LIMIT)))
    except (TypeError, ValueError):
        return [], "closing_within_days 와 limit 는 정수다"
    order = str(params.get("order") or "최신순")
    if order not in ORDERS:
        return [], f"정렬은 {', '.join(ORDERS)} 중 하나다"
    keyword = str(params.get("keyword") or "").strip()
    categories = [category] if category else list(HOUSING)
    return [Query(c, code, region, status, keyword, closing, limit, order) for c in categories], None


def form_of(query: Query, today: date, page: int = 1) -> dict[str, str]:
    """게시판 검색 폼과 같은 값. 빠진 칸이 있으면 게시판이 오류 페이지를 준다."""
    cat = CATEGORIES[query.category]
    upp, _, ais = query.code.partition("/")
    if query.closing_within_days is None:
        period = ("0", today - timedelta(days=DEFAULT_PERIOD_DAYS), today)
    else:
        period = ("1", today, today + timedelta(days=query.closing_within_days))
    page_size = PAGE_SIZES[-1] if query.exhaustive else next(size for size in PAGE_SIZES if size >= query.limit)
    form = {
        "mi": cat.menu, "currPage": str(page), "srchY": "Y", "indVal": "N", "srchFilter": "N",
        "panId": "", "ccrCnntSysDsCd": "", "prevListCo": "", "viewType": "", "netbgn": "",
        "srchUppAisTpCd": upp or cat.srch, "uppAisTpCd": upp or cat.upp, "aisTpCd": ais, "srchAisTpCd": ais,
        "mvinQf": "0", "cnpCd": query.region, "panSs": query.status,
        "schTy": period[0], "startDt": period[1].isoformat(), "endDt": period[2].isoformat(),
        "panNm": query.keyword, "listCo": str(page_size),
    }
    if page > 1:
        # 새 검색(srchY=Y)으로 보내면 게시판이 1쪽을 다시 준다. 앞 쪽 크기(prevListCo)까지 있어야 다음 쪽이다
        form.update(srchY="N", prevListCo=str(page_size))
    return form


def unique(notices: list[Notice]) -> list[Notice]:
    """게시판 순서를 지키고 같은 공고는 처음 것만. 쪽 사이에 새 공고가 올라오면 한 칸씩 밀려 겹친다."""
    first: dict[str, Notice] = {}
    for notice in notices:
        first.setdefault(notice.id, notice)
    return list(first.values())


def pages_of(total: int | None) -> int:
    """전부 볼 때 받을 쪽 수. 마지막 쪽을 넘기면 게시판이 마지막 쪽을 다시 주므로 건수로 멈춘다."""
    if not total:
        return 1
    return min(MAX_PAGES, -(-total // PAGE_SIZES[-1]))


def parse_list(page: str) -> tuple[int | None, list[Notice]]:
    """목록 페이지에서 전체 건수와 공고들. 게시판 표가 없으면 (None, [])."""
    body = _TBODY_RE.search(page)
    if body is None:
        return None, []
    total_match = _TOTAL_RE.search(page)
    total = int(total_match.group(1).replace(",", "")) if total_match else None
    notices = []
    for row in _ROW_RE.findall(body.group(1)):
        link = _LINK_RE.search(row)
        title = _TITLE_RE.search(row)
        cells = [text_of(cell) for cell in _TD_RE.findall(row)]
        if link is None or title is None or len(cells) < 9:
            continue
        notices.append(Notice(
            id=notice_id(*link.groups()), kind=cells[1], title=text_of(title.group(1)), region=cells[3],
            posted=cells[5], closes=cells[6], status=cells[7],
        ))
    return total, notices


def by_deadline(notices: list[Notice], today: date) -> list[Notice]:
    """마감이 가까운 순. 마감일이 없거나 지난 공고는 뒤로, 그 안에서는 게시판 순서를 지킨다."""

    def key(notice: Notice) -> tuple[int, int]:
        close = parse_date(notice.closes)
        if close is None or close < today:
            return (1, 0)
        return (0, (close - today).days)

    return sorted(notices, key=key)


def render_list(
    query_text: str, found: list[tuple[str, int | None, list[Notice]]], limit: int, today: date, order: str = "최신순"
) -> str:
    lines = [f"LH 청약 공고 ({query_text}, {order}). 마감은 KST {today.isoformat()} 기준"]
    shown = 0
    for category, total, notices in found:
        if order == "마감순":
            notices = by_deadline(notices, today)
        lines.append(f"\n[{category}] 전체 {total if total is not None else '?'}건, {min(len(notices), limit)}건 표시")
        for n in notices[:limit]:
            label = deadline_label(parse_date(n.closes), today)
            lines.append(
                f"- [{label}] {n.title}\n  유형 {n.kind} | 지역 {n.region} | 게시 {n.posted} | 마감 {n.closes or '-'}"
                f" | 상태 {n.status} | id {n.id}\n  {detail_url(n.id)}"
            )
            shown += 1
    lines.append("\n조건에 맞는 공고가 없다." if shown == 0 else f"\n{LIST_HINT}")
    return "\n".join(lines)


def parse_detail(page: str) -> dict[str, Any] | None:
    """상세 페이지의 제목, 게시 정보, 공고문 파일, 주택형 표, 공급과 일정 절. 공고 표식이 없으면 None."""
    title = re.search(r"<h3>([^<]+)</h3>", page)
    facts = re.findall(r'<ul class="bbsV_data">([\s\S]*?)</ul>', page)
    if title is None or not facts:
        return None
    info: dict[str, str] = {}
    for label, value in re.findall(r"<li><strong>([^<]+)</strong>([\s\S]*?)</li>", facts[-1]):
        info[text_of(label)] = text_of(value)
    file_ids = [(fid, text_of(name)) for fid, name in re.findall(r"fileDownLoad\('(\d+)'\);\">([^<]+)</a>", page)]
    files = [name for _, name in file_ids]
    units: list[list[str]] = []
    for caption, table in re.findall(r"<caption>([^<]*?)(?:<br>[^<]*)?</caption>([\s\S]*?)</table>", page):
        if caption.strip().startswith("주택형 안내"):
            units = [[c for c in row if c not in UNIT_NOISE] for row in table_rows(table)]
            break
    sections: dict[str, str] = {}
    parts = re.split(r'<h3 class="tit1">([^<]+)</h3>', page)
    for name, body in zip(parts[1::2], parts[2::2], strict=False):
        name = name.strip()
        if name in ("공급정보", "공급일정", "접수처정보") and name not in sections:
            body = body.split("</section>", 1)[0].split('<h4 class="tit2">단지 관련 이미지', 1)[0]
            body = _TABLE_RE.sub(lambda m: "\n".join(" | ".join(row) for row in table_rows(m.group(0))) + "\n", body)
            sections[name] = "\n".join(lines_of(body))[:DETAIL_TEXT_LIMIT]
    return {
        "title": text_of(title.group(1)), "info": info, "files": files, "file_ids": file_ids, "units": units,
        "sections": sections,
    }


def unit_price(units: list[list[str]], unit: str) -> tuple[str, str, int] | None:
    """주택형 표에서 금액 하나. (주택형, 금액 칸 이름, 원). unit 을 비우면 첫 주택형.

    '55A' 는 '55.9000A' 처럼 면적 정수부와 끝 글자로 맞춘다. 금액 칸은 분양가, 없으면 임대보증금.
    """
    if len(units) < 2:
        return None
    header = units[0]
    column = next((i for i, name in enumerate(header) if "분양가" in name), None)
    if column is None:
        column = next((i for i, name in enumerate(header) if "보증금" in name), None)
    if column is None:
        return None
    wanted = re.fullmatch(r"\s*(\d+)(?:\.\d+)?\s*([A-Za-z]*)\s*(?:형|타입)?\s*", unit or "")
    for row in units[1:]:
        if column >= len(row):
            continue
        if unit and not _same_unit(row[0], wanted, unit):
            continue
        amount = row[column].replace(",", "")
        if amount.isdigit():
            return row[0], header[column], int(amount)
    return None


def _same_unit(name: str, wanted: re.Match[str] | None, unit: str) -> bool:
    if wanted is None:
        return unit.strip() in name
    have = re.fullmatch(r"0*(\d+)(?:\.\d+)?([A-Za-z]*)", name.strip())
    if have is None:
        return unit.strip() in name
    return int(have.group(1)) == int(wanted.group(1)) and (
        not wanted.group(2) or have.group(2).upper() == wanted.group(2).upper()
    )


def render_detail(nid: str, detail: dict[str, Any], today: date) -> str:
    info = detail["info"]
    lines = [f"LH 공고 상세: {detail['title']}", f"id {nid}", detail_url(nid)]
    lines += [f"{k}: {v}" for k, v in info.items() if k != "유의사항"]
    if "마감일" in info:
        lines.append(f"마감(KST {today.isoformat()} 기준): {deadline_label(parse_date(info['마감일']), today)}")
    if detail["files"]:
        lines.append("공고문 파일: " + ", ".join(detail["files"]))
    if detail["units"]:
        lines.append("\n주택형 안내")
        lines += [" | ".join(row) for row in detail["units"]]
    for name, body in detail["sections"].items():
        lines.append(f"\n{name}\n{body}")
    if unit_price(detail["units"], "") is not None:
        lines.append(f"\n{DETAIL_HINT.format(nid=nid)}")
    return "\n".join(lines)


class LhNoticeTool(JarvisTool):
    """읽기만 한다. 청약 신청, 로그인, 파일 내려받기는 하지 않는다."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    def __init__(self, fetch: Fetch | None = None, today: Callable[[], date] = kst_today) -> None:
        self._fetch = fetch or fetch_html
        self._today = today

    async def execute(
        self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None
    ) -> ToolResultMessage:
        today = self._today()
        nid = str(params.get("id") or "").strip()
        try:
            if nid:
                return await self._detail(tool_call_id, nid, today)
            return await self._search(tool_call_id, params, today)
        except FetchError as exc:
            return _result(tool_call_id, f"LH 게시판 조회 실패: {exc}", True)

    async def _search(self, tool_call_id: str, params: dict[str, Any], today: date) -> ToolResultMessage:
        queries, reason = build_queries(params)
        if reason is not None:
            return _result(tool_call_id, reason, True)
        try:
            found = await self.search(queries, today)
        except ValueError as exc:
            return _result(tool_call_id, str(exc), True)
        first = queries[0]
        return _result(tool_call_id, render_list(_describe(params, first), found, first.limit, today, first.order))

    async def search(self, queries: list[Query], today: date) -> list[tuple[str, int | None, list[Notice]]]:
        """분류마다 (분류, 전체 건수, 공고). 목록 표가 없으면 ValueError, 게시판 장애는 FetchError."""
        found = []
        for query in queries:
            total, notices = parse_list(await self._fetch(LIST_URL, form_of(query, today)))
            if total is None and not notices:
                raise ValueError(f"LH 게시판({query.category})이 예상한 목록 표를 주지 않았다")
            if query.exhaustive:
                for page in range(2, pages_of(total) + 1):
                    notices += parse_list(await self._fetch(LIST_URL, form_of(query, today, page)))[1]
                notices = unique(notices)
            found.append((query.category, total, notices))
        return found

    async def _detail(self, tool_call_id: str, nid: str, today: date) -> ToolResultMessage:
        try:
            detail = await self.detail(nid)
        except ValueError as exc:
            return _result(tool_call_id, str(exc), True)
        return _result(tool_call_id, render_detail(nid, detail, today))

    async def detail(self, nid: str) -> dict[str, Any]:
        """공고 상세. 틀린 id 나 읽지 못한 화면은 ValueError, 게시판 장애는 FetchError."""
        if _ID_RE.match(nid) is None:
            raise ValueError(f"id 형식이 아니다: {nid} (lh_notice 목록 결과의 id 를 그대로 쓴다)")
        url = detail_url(nid)
        base, _, query = url.partition("?")
        detail = parse_detail(await self._fetch(base, dict(p.split("=", 1) for p in query.split("&"))))
        if detail is None:
            raise ValueError(f"공고 상세를 읽지 못했다(없는 공고이거나 화면이 바뀌었다): {url}")
        return detail

    async def price_of(self, nid: str, unit: str) -> tuple[float, str]:
        """공고의 주택형 금액과 그 근거 글. housing_loan 이 공고 id 로 원금을 정할 때 쓴다."""
        detail = await self.detail(nid)
        found = unit_price(detail["units"], unit)
        if found is None:
            names = ", ".join(row[0] for row in detail["units"][1:]) or "없음"
            wanted = unit or "(첫 주택형)"
            raise ValueError(f"'{detail['title']}' 에서 주택형 {wanted} 의 금액을 찾지 못했다(주택형: {names})")
        name, column, amount = found
        return float(amount), f"{detail['title']} {name} {column}"


def _describe(params: dict[str, Any], query: Query) -> str:
    parts = [params.get("subtype") or params.get("category") or "임대+분양", params.get("region") or "전국"]
    if query.status:
        parts.append(query.status)
    if query.keyword:
        parts.append(f"키워드 '{query.keyword}'")
    if query.closing_within_days is not None:
        parts.append(f"{query.closing_within_days}일 안 마감")
    return ", ".join(str(p) for p in parts)


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TOOL_NAME, content=[TextContent(text=text)], is_error=is_error
    )
