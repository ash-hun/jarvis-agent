"""[core] SH 공개 공고 게시판을 키워드, 공고 종류로 조회하고 상세 본문과 첨부 미리보기를 읽는 sh_notice 도구."""

import re
import json
import asyncio
from typing import Any
from dataclasses import dataclass

from jarvis.core.tools.housing.fetch import Fetch, FetchError, fetch_html
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.housing.markup import lines_of, text_of
from jarvis.core.tools.registry import JarvisTool

TOOL_NAME = "sh_notice"
SH_BASE = "https://www.i-sh.co.kr"
# 게시판은 한 쪽에 10건 고정이다. 더 보려면 page 를 넘긴다
PAGE_SIZE = 10
MAX_PAGE = 1000
CONTENT_LIMIT = 3000
KEYWORD_MAX = 100
# 검색어로 들어오면 버리는 지역 말
REGION_WORDS = frozenset({"서울", "서울시", "서울특별시", "경기", "경기도", "인천", "수도권", "전국"})


@dataclass(frozen=True)
class Board:
    """공고 종류마다 게시판 경로와 분류 값. 전체 게시판은 여러 분류를 한 번에 받는다."""

    name: str
    path: str
    query: tuple[tuple[str, str], ...]


BOARDS: dict[str, Board] = {
    "임대": Board("주택임대", "/app/lay2/program/S1T294C297/www/brd/m_247", (("multi_itm_seq", "2"),)),
    "분양": Board("주택분양", "/app/lay2/program/S1T294C296/www/brd/m_244", (("multi_itm_seq", "1"),)),
    "주거복지": Board("주택매입", "/app/lay2/program/S1T294C3379/www/brd/m_247", (("multi_itm_seq", "512"),)),
    "입주": Board("입주안내", "/app/lay2/program/S1T294C298/www/brd/m_248", (("multi_itm_seq", "4"),)),
    "토지": Board("토지", "/app/lay2/program/S1T294C299/www/brd/m_255", (("multi_itm_seq", "8"),)),
    "상가": Board("상가/공장", "/app/lay2/program/S1T294C300/www/brd/m_256", (("multi_itm_seq", "16"),)),
    "보상": Board("보상/이주", "/app/lay2/program/S1T294C301/www/brd/m_257", (("multi_itm_seq", "32"),)),
    "기타": Board("기타", "/app/lay2/program/S1T294C304/www/brd/m_260", (("multi_itm_seq", "256"),)),
    "전체": Board(
        "전체", "/app/lay2/program/S1T294C295/www/brd/m_241", (("multi_itm_seqs", "1,2,4,8,16,32,64,128,256,512"),)
    ),
}
# 공개 게시판에는 상태 칸이 없어 제목 말로 짐작한다. 앞의 것이 먼저 맞는다
STATUS_BY_TITLE = (
    ("당첨/발표", re.compile(r"당첨|발표")),
    ("마감/결과", re.compile(r"마감|결과|경쟁률|완료|종료")),
    ("모집/접수", re.compile(r"모집|신청|접수|공고")),
)
STATUSES = tuple(label for label, _ in STATUS_BY_TITLE)

TOOL_DESCRIPTION = (
    "서울주택도시공사(SH, i-sh.co.kr) 공고 및 공지 게시판을 직접 읽는다."
    " 목록은 키워드(제목 또는 본문)와 공고 종류(임대, 분양, 주거복지=주택매입 게시판, 토지, 상가 등)로 거른다."
    " seq 를 주면 그 글의 본문, 등록일, 담당부서, 첨부파일 이름과 크기, 미리보기 링크를 본다."
    " 상태는 게시판에 없어 제목 말로 짐작한 값이다. LH 공고는 lh_notice 를 쓴다."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "seq": {"type": "string", "description": "상세를 볼 글 번호. 목록 결과의 seq 그대로"},
        "category": {"type": "string", "enum": list(BOARDS), "description": "공고 종류. 기본 임대"},
        "keyword": {"type": "string", "description": "찾을 말. 예: 행복주택. 지역 이름은 넣지 않는다(SH 는 서울뿐)"},
        "search_in": {"type": "string", "enum": ["제목", "본문"], "description": "keyword 를 찾을 곳. 기본 제목"},
        "status": {"type": "string", "enum": list(STATUSES), "description": "제목으로 짐작한 상태로 거른다"},
        "page": {"type": "integer", "description": f"쪽 번호(한 쪽 {PAGE_SIZE}건, 기본 1)"},
    },
}

_TOTAL_RE = re.compile(r"총\s*<strong[^>]*>\s*([\d,]+)\s*</strong>\s*건")
_TBODY_RE = re.compile(r'id="listTb"[\s\S]*?<tbody[^>]*>([\s\S]*?)</tbody>')
_ROW_RE = re.compile(r"<tr\b[^>]*>([\s\S]*?)</tr>")
_SEQ_RE = re.compile(r"getDetailView\('(\d+)'\)")
_TD_RE = re.compile(r"<td\b[^>]*>([\s\S]*?)</td>")


@dataclass(frozen=True)
class Post:
    seq: str
    title: str
    department: str
    registered: str
    views: str
    status: str


def title_status(title: str) -> str:
    for label, pattern in STATUS_BY_TITLE:
        if pattern.search(title):
            return label
    return "알 수 없음"


def list_url(board: Board) -> str:
    return f"{SH_BASE}{board.path}/list.do"


def view_url(board: Board, seq: str) -> str:
    # 전체 게시판의 글도 분류 게시판 주소로 열린다. 전체는 seq 만으로 연다
    query = "&".join(f"{k}={v}" for k, v in board.query if k == "multi_itm_seq")
    return f"{SH_BASE}{board.path}/view.do?" + (f"{query}&" if query else "") + f"seq={seq}"


def list_query(board: Board, keyword: str, search_in: str, page: int) -> dict[str, str]:
    """검색어가 있으면 srchTp 를 꼭 붙인다. 없으면 게시판이 검색어를 무시한다."""
    query = dict(board.query)
    query["page"] = str(page)
    if keyword:
        query["srchWord"] = keyword
        query["srchTp"] = "1" if search_in == "본문" else "0"
    return query


def parse_list(page: str) -> tuple[int | None, list[Post]] | None:
    """목록 페이지의 전체 건수와 글. 게시판 표가 없으면 None(막힘이나 점검 화면)."""
    body = _TBODY_RE.search(page)
    if body is None:
        return None
    total_match = _TOTAL_RE.search(page)
    posts = []
    for row in _ROW_RE.findall(body.group(1)):
        seq = _SEQ_RE.search(row)
        cells = [text_of(cell) for cell in _TD_RE.findall(row)]
        if seq is None or len(cells) < 5:
            continue
        title = re.sub(r"^NEW\s*", "", cells[1])
        posts.append(Post(seq.group(1), title, cells[2], cells[3], cells[4], title_status(title)))
    return (int(total_match.group(1).replace(",", "")) if total_match else None), posts


def parse_detail(page: str) -> dict[str, Any] | None:
    """상세 페이지의 제목, 등록일, 조회수, 담당부서, 본문, 첨부. 상세 표가 없으면 None."""
    caption = re.search(r'class="detailTable[^"]*"[\s\S]*?<caption>([\s\S]*?)</caption>', page)
    if caption is None:
        return None
    registered = re.search(r"등록일\s*:\s*</strong>\s*([\d.\-]+)", page)
    views = re.search(r"조회수\s*:\s*</strong>\s*([\d,]+)", page)
    department = re.search(r"<span>담당부서</span>\s*:\s*([^<]+)", page)
    content = re.search(r'<td\b[^>]*class="cont"[^>]*>([\s\S]*?)</td>', page)
    return {
        "title": text_of(caption.group(1)),
        "registered": registered.group(1) if registered else "",
        "views": views.group(1) if views else "",
        "department": text_of(department.group(1)) if department else "",
        "content": "\n".join(lines_of(content.group(1)))[:CONTENT_LIMIT] if content else "",
        "attachments": parse_attachments(page),
    }


def parse_attachments(page: str) -> list[dict[str, str]]:
    """첨부 목록은 페이지 스크립트의 downList 가 정본이다. 확장자 아이콘 견본(주석 속 앵커)은 첨부가 아니다."""
    match = re.search(r"initParam\.downList\s*=\s*(\[[\s\S]*?\])\s*;", page)
    if match is None:
        return []
    try:
        files = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    attachments = []
    for item in files if isinstance(files, list) else []:
        size = int(item.get("fileSize") or 0)
        preview = (
            f"{SH_BASE}/app/com/util/htmlConverter.do?brd_id={item.get('brdId', '')}&seq={item.get('seq', '')}"
            f"&data_tp={item.get('fileTp', 'A')}&file_seq={item.get('fileSeq', '')}"
        )
        attachments.append({"name": str(item.get("oriFileNm", "")), "size": f"{size / 1024:.0f}KB", "preview": preview})
    return attachments


class ShNoticeTool(JarvisTool):
    """읽기만 한다. 로그인, 청약 신청, 파일 내려받기는 하지 않는다."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    def __init__(self, fetch: Fetch | None = None) -> None:
        self._fetch = fetch or fetch_html

    async def execute(
        self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None
    ) -> ToolResultMessage:
        category = str(params.get("category") or "임대")
        if category not in BOARDS:
            return _result(tool_call_id, f"모르는 공고 종류: {category} (가능: {', '.join(BOARDS)})", True)
        board = BOARDS[category]
        seq = str(params.get("seq") or "").strip()
        try:
            if seq:
                return await self._detail(tool_call_id, board, seq)
            return await self._search(tool_call_id, board, category, params)
        except FetchError as exc:
            return _result(tool_call_id, f"SH 게시판 조회 실패: {exc}", True)

    async def _search(
        self, tool_call_id: str, board: Board, category: str, params: dict[str, Any]
    ) -> ToolResultMessage:
        keyword = str(params.get("keyword") or "").strip()[:KEYWORD_MAX]
        # 실서버에서 모델이 지역을 검색어로 넣어 제목에 '서울'이 든 옛 글만 받았다. 지역 말은 버린다
        dropped = keyword if keyword in REGION_WORDS else ""
        keyword = "" if dropped else keyword
        search_in = str(params.get("search_in") or "제목")
        status = str(params.get("status") or "")
        if status and status not in STATUSES:
            return _result(tool_call_id, f"모르는 상태: {status} (가능: {', '.join(STATUSES)})", True)
        try:
            page = min(MAX_PAGE, max(1, int(params.get("page") or 1)))
        except (TypeError, ValueError):
            return _result(tool_call_id, "page 는 정수다", True)
        query = list_query(board, keyword, search_in, page)
        parsed = parse_list(await self._fetch(list_url(board), query))
        if parsed is None:
            return _result(tool_call_id, "SH 게시판이 목록 표를 주지 않았다(접속 제한이나 점검 화면일 수 있다)", True)
        total, posts = parsed
        if status:
            posts = [p for p in posts if p.status == status]
        head = f"SH 공고 ({board.name}" + (f", {search_in} '{keyword}'" if keyword else "") + f", {page}쪽)"
        lines = [f"{head}. 전체 {total if total is not None else '?'}건, 이 쪽 {len(posts)}건"]
        if status:
            lines.append(f"상태 '{status}'는 제목 말로 짐작해 거른 결과다")
        if dropped:
            lines.append(f"'{dropped}'는 지역이라 검색어에서 뺐다. SH 게시판은 서울 공고만 있다")
        for p in posts:
            lines.append(
                f"- {p.title}\n  등록 {p.registered} | {p.department} | 조회 {p.views} | 상태(제목 짐작) {p.status}"
                f" | seq {p.seq}\n  {view_url(board, p.seq)}"
            )
        if not posts:
            lines.append("조건에 맞는 글이 없다.")
        if category == "주거복지":
            lines.append("주거복지는 SH 공개 게시판의 '주택매입' 분류로 찾았다.")
        return _result(tool_call_id, "\n".join(lines))

    async def _detail(self, tool_call_id: str, board: Board, seq: str) -> ToolResultMessage:
        if not seq.isdigit():
            return _result(tool_call_id, f"seq 는 숫자다: {seq}", True)
        url = view_url(board, seq)
        base, _, query = url.partition("?")
        detail = parse_detail(await self._fetch(base, dict(p.split("=", 1) for p in query.split("&"))))
        if detail is None:
            return _result(tool_call_id, f"글 상세를 읽지 못했다(없는 글이거나 다른 종류 게시판의 글이다): {url}", True)
        lines = [
            f"SH 공고 상세: {detail['title']}",
            f"seq {seq} | 등록 {detail['registered']} | 조회 {detail['views']} | 담당 {detail['department']}",
            f"상태(제목 짐작) {title_status(detail['title'])}",
            url,
        ]
        if detail["attachments"]:
            lines.append("\n첨부")
            lines += [f"- {a['name']} ({a['size']})\n  미리보기 {a['preview']}" for a in detail["attachments"]]
        if detail["content"]:
            lines.append(f"\n본문\n{detail['content']}")
        return _result(tool_call_id, "\n".join(lines))


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TOOL_NAME, content=[TextContent(text=text)], is_error=is_error
    )
