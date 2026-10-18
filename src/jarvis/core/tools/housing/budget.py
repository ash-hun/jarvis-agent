"""[core] 총예산, 현금, 월 부담 상한으로 열린 LH 공고를 골라 대출과 월 부담까지 계산하는 housing_budget 도구."""

import re
import asyncio
from typing import Any
from datetime import date
from collections.abc import Callable
from dataclasses import dataclass, replace

from jarvis.core.tools.housing.lh_notice import LhNoticeTool, Notice, build_queries, detail_url, resolve_region
from jarvis.core.tools.housing.fetch import Fetch, FetchBytes, FetchError, fetch_bytes, fetch_html, kst_today
from jarvis.core.tools.housing.notice_pdf import RentTerm, notice_rent_terms, pdf_text, pick_notice_pdf
from jarvis.core.tools.housing.rental_complex import ComplexUnit, fetch_complexes, match_complex
from jarvis.core.tools.housing.markup import deadline_label, parse_date
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.housing.loan import annuity_payment, won
from jarvis.core.tools.registry import JarvisTool

TOOL_NAME = "housing_budget"
# 사용자가 금리, 기간을 주지 않을 때의 가정. 결과 첫 줄에 밝힌다
DEFAULT_RATE = 4.0
DEFAULT_YEARS = 30
DEFAULT_LIMIT = 3
MAX_LIMIT = 10
# ponytail: 상세를 공고 20건까지만 연다(게시판 부하와 응답 시간), 열린 공고가 늘면 지역이나 유형으로 나눠 부른다
MAX_DETAILS = 20
# ponytail: 공고문 PDF 는 한 번에 8건까지만 받는다(건당 1MB 안팎, 수 초), 더 필요하면 지역을 나눠 부른다
MAX_PDFS = 8
LIST_SIZE = 50
OPEN_STATUS = "공고중"
DEFAULT_REGIONS = ("전국",)

TOOL_DESCRIPTION = (
    "총예산, 보유 현금, 월 부담 상한으로 지금 공고중인 LH 공고 중 조건에 맞는 것을 골라 추천한다."
    " 공고 목록, 공고마다 상세 금액(분양가, 임대보증금, 월임대료), 대출(총액 - 현금), 월 부담 계산을 한 번에 한다."
    " 상세에 금액이 없는 임대 공고는 공고문 PDF 의 임대조건 표, 그래도 없으면 LH 임대주택검색의 같은 단지 금액을 쓴다."
    " 금액을 끝내 모르면 공고문 확인 목록에 따로 적는다."
    " '3억 안쪽, 현금 1억 2천, 월 200만원 이하 공고 추천' 같은 요청에 쓴다. 금액은 원 단위."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "budget": {"type": "number", "description": "총예산(원). 분양가나 보증금이 이 안이어야 한다"},
        "cash": {"type": "number", "description": "보유 현금(원). 대출 = 분양가나 보증금 - 현금"},
        "monthly_limit": {"type": "number", "description": "월 부담 상한(원). 대출 상환 + 월임대료"},
        "regions": {"type": "string", "description": "지역. 쉼표로 여럿. 예: 서울,경기. 비우면 전국"},
        "annual_rate_percent": {"type": "number", "description": f"대출 연 금리(%). 비우면 {DEFAULT_RATE}% 가정"},
        "years": {"type": "integer", "description": f"분양 대출 기간(년). 비우면 {DEFAULT_YEARS}년 가정"},
        "limit": {"type": "integer", "description": f"추천 수(기본 {DEFAULT_LIMIT}, 최대 {MAX_LIMIT})"},
    },
    "required": ["budget", "cash"],
}


@dataclass(frozen=True)
class Option:
    """공고의 주택형 하나와 그 금액. sale 이면 분양가, 아니면 임대보증금."""

    unit: str
    price: int
    rent: int
    sale: bool
    source: str


@dataclass(frozen=True)
class Plan:
    notice: Notice
    option: Option
    loan: float
    repay: float  # 대출 월 상환(분양) 또는 월 이자(임대 보증금 대출)
    fits: int = 1  # 조건에 맞은 주택형 수

    @property
    def monthly(self) -> float:
        return self.repay + self.option.rent


@dataclass(frozen=True)
class Terms:
    budget: float
    cash: float
    monthly_limit: float | None
    rate: float
    years: int


def number(text: str) -> int | None:
    digits = text.replace(",", "").strip()
    return int(digits) if re.fullmatch(r"\d+", digits) and int(digits) > 0 else None


def options_from_units(units: list[list[str]]) -> list[Option]:
    """상세 주택형 표의 금액. 분양가 칸이 있으면 분양, 없으면 보증금과 월임대료. 숫자가 아닌 칸은 뺀다."""
    if len(units) < 2:
        return []
    header = units[0]

    def column(word: str) -> int | None:
        return next((i for i, name in enumerate(header) if word in name), None)

    sale_col, deposit_col, rent_col = column("분양가"), column("보증금"), column("임대료")
    price_col = sale_col if sale_col is not None else deposit_col
    if price_col is None:
        return []
    options = []
    for row in units[1:]:
        price = number(row[price_col]) if price_col < len(row) else None
        if price is None:
            continue
        rent = number(row[rent_col]) if rent_col is not None and rent_col < len(row) else None
        options.append(Option(row[0], price, rent or 0, sale_col is not None, "공고 상세"))
    return options


def options_from_terms(terms: list[RentTerm]) -> list[Option]:
    return [Option(t.unit, t.deposit, t.rent, False, "공고문 PDF 임대조건") for t in terms]


def options_from_complex(rows: list[ComplexUnit]) -> list[Option]:
    return [
        Option(f"{r.name} {r.area:g}㎡", r.deposit, r.rent, False, "임대주택검색 단지 금액")
        for r in rows
    ]


def plan_for(notice: Notice, options: list[Option], terms: Terms) -> Plan | None:
    """예산과 월 상한을 지키는 주택형 중 월 부담이 가장 작은 것. 없으면 None."""
    best: Plan | None = None
    fits = 0
    for option in options:
        if option.price > terms.budget:
            continue
        loan = max(0.0, option.price - terms.cash)
        if option.sale:
            repay = annuity_payment(loan, terms.rate / 100 / 12, terms.years * 12)
        else:
            # 보증금 대출(전세자금 대출 꼴)은 만기일시 상환이라 매달 이자만 낸다
            repay = loan * terms.rate / 100 / 12
        plan = Plan(notice, option, loan, repay)
        if terms.monthly_limit is not None and plan.monthly > terms.monthly_limit:
            continue
        fits += 1
        if best is None or plan.monthly < best.monthly:
            best = plan
    return replace(best, fits=fits) if best is not None else None


def render(
    terms: Terms, regions: list[str], plans: list[Plan], over: list[Notice], unknown: list[Notice],
    skipped: int, limit: int, today: date,
) -> str:
    cap = f", 월 부담 {won(terms.monthly_limit)} 이하" if terms.monthly_limit is not None else ""
    lines = [
        f"LH 공고 예산 추천 ({', '.join(regions)} | 총예산 {won(terms.budget)}, 현금 {won(terms.cash)}{cap})",
        f"가정: 연 {terms.rate:g}%, 분양은 {terms.years}년 원리금균등, 임대 보증금 대출은 매달 이자만."
        f" 대출 = 금액 - 현금. 마감은 KST {today.isoformat()} 기준",
    ]
    plans = sorted(plans, key=lambda p: p.monthly)
    lines.append(f"\n조건에 맞는 공고 {len(plans)}건" + (f", {min(len(plans), limit)}건 표시" if plans else ""))
    for index, plan in enumerate(plans[:limit], 1):
        n, o = plan.notice, plan.option
        label = deadline_label(parse_date(n.closes), today)
        kind = "분양가" if o.sale else "보증금"
        parts = [f"대출 {won(plan.loan)}", f"월 부담 {won(plan.monthly)}"]
        detail = f"대출 상환 {won(plan.repay)}" if o.sale else f"대출 이자 {won(plan.repay)}"
        if o.rent:
            detail += f" + 월임대료 {won(o.rent)}"
        lines.append(
            f"{index}. [{label}] {n.title}\n   {n.kind} | {n.region} | id {n.id}\n"
            f"   {o.unit} {kind} {won(o.price)} ({o.source}) → {', '.join(parts)} ({detail})\n"
            f"   조건에 맞는 주택형 {plan.fits}개 중 월 부담이 가장 작은 것\n   {detail_url(n.id)}"
        )
    if over:
        lines.append(f"\n예산이나 월 상한을 넘는 공고 {len(over)}건: " + ", ".join(n.title for n in over[:5]))
    if unknown:
        lines.append(f"\n금액을 찾지 못한 공고 {len(unknown)}건(상세, 공고문 PDF, 임대주택검색에 금액 없음. 첨부 확인)")
        lines += [f"- [{deadline_label(parse_date(n.closes), today)}] {n.title} | {detail_url(n.id)}" for n in unknown]
    if skipped:
        lines.append(f"\n상세를 {MAX_DETAILS}건까지만 열어 {skipped}건은 보지 않았다. 지역을 나눠 다시 부른다.")
    lines.append(
        "\n답할 때 위 숫자를 그대로 쓰고 가정(금리, 기간, 상환 방식)을 밝힌다."
        " 주택형 이름의 공급대상(수급자, 청년, 「가」군 등)은 신청 자격이라 맞는지 확인하라고 적는다."
        " 매입임대와 전세임대는 집마다 금액이 달라 공고문 확인 목록에 남는다. SH 공고는 금액이 첨부에만 있어 빠진다."
    )
    return "\n".join(lines)


class HousingBudgetTool(JarvisTool):
    """읽기와 계산만 한다. 같은 날 같은 인자면 같은 답이다(게시판이 바뀌지 않는 한)."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    def __init__(
        self,
        notices: LhNoticeTool,
        fetch: Fetch | None = None,
        today: Callable[[], date] = kst_today,
        fetch_file: FetchBytes | None = None,
        read_pdf: Callable[[bytes], str] = pdf_text,
    ) -> None:
        self._notices = notices
        self._fetch = fetch or fetch_html
        self._fetch_file = fetch_file or fetch_bytes
        self._read_pdf = read_pdf
        self._today = today

    async def execute(
        self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None
    ) -> ToolResultMessage:
        try:
            terms, regions, limit = parse_terms(params)
        except (TypeError, ValueError) as exc:
            return _result(tool_call_id, f"조건을 읽을 수 없다: {exc}", True)
        try:
            return _result(tool_call_id, await self._recommend(terms, regions, limit))
        except (FetchError, ValueError) as exc:
            return _result(tool_call_id, f"LH 조회 실패: {exc}", True)

    async def _recommend(self, terms: Terms, regions: list[str], limit: int) -> str:
        today = self._today()
        notices: dict[str, Notice] = {}
        for region in regions:
            queries, reason = build_queries({"region": region, "status": OPEN_STATUS, "limit": LIST_SIZE})
            if reason is not None:
                raise ValueError(reason)
            for _, _, found in await self._notices.search(queries, today):
                for n in found:
                    close = parse_date(n.closes)
                    if close is None or close >= today:
                        notices.setdefault(n.id, n)
        ordered = sorted(notices.values(), key=lambda n: parse_date(n.closes) or date.max)
        complexes: dict[str, list[ComplexUnit]] = {}
        plans, over, unknown = [], [], []
        pdfs = 0
        for notice in ordered[:MAX_DETAILS]:
            detail = await self._notices.detail(notice.id)
            options = options_from_units(detail["units"])
            pdf_id = pick_notice_pdf(detail["file_ids"])
            if not options and pdf_id is not None and pdfs < MAX_PDFS:
                pdfs += 1
                options = options_from_terms(await self._pdf_terms(pdf_id, detail_url(notice.id)))
            if not options:
                options = options_from_complex(await self._complex_rows(notice, complexes))
            if not options:
                unknown.append(notice)
                continue
            plan = plan_for(notice, options, terms)
            if plan is None:
                over.append(notice)
            else:
                plans.append(plan)
        skipped = max(0, len(ordered) - MAX_DETAILS)
        return render(terms, regions, plans, over, unknown, skipped, limit, today)

    async def _pdf_terms(self, file_id: str, referer: str) -> list[RentTerm]:
        """공고문을 못 받거나 못 읽으면 빈 목록. 한 공고의 실패로 추천 전체를 멈추지 않는다."""
        try:
            return await notice_rent_terms(self._fetch_file, file_id, referer, self._read_pdf)
        except Exception:  # FetchError, 깨진 PDF(pypdf 의 여러 예외)
            return []

    async def _complex_rows(self, notice: Notice, cache: dict[str, list[ComplexUnit]]) -> list[ComplexUnit]:
        """공고 지역의 임대 단지 전체를 한 번만 받아 공고 제목으로 단지를 고른다."""
        code = resolve_region(notice.region.split(" 외")[0])
        if not code:
            return []
        if code not in cache:
            cache[code] = await fetch_complexes(self._fetch, code)
        return match_complex(notice.title, notice.kind, cache[code])


def parse_terms(params: dict[str, Any]) -> tuple[Terms, list[str], int]:
    """인자를 검사한 계산 조건, 지역 목록, 추천 수. 틀리면 ValueError."""
    budget = float(params.get("budget") or 0)
    cash = float(params.get("cash") or 0)
    if budget <= 0 or cash < 0:
        raise ValueError("budget 은 0 보다 크고 cash 는 0 이상이다")
    limit_value = params.get("monthly_limit")
    monthly_limit = float(limit_value) if limit_value not in (None, "", 0) else None
    rate = float(params.get("annual_rate_percent") or DEFAULT_RATE)
    years = int(params.get("years") or DEFAULT_YEARS)
    if not 0 <= rate <= 100 or not 1 <= years <= 50:
        raise ValueError("금리는 0~100%, 기간은 1~50년이다")
    raw = str(params.get("regions") or "").replace("/", ",")
    regions = [r.strip() for r in raw.split(",") if r.strip()] or list(DEFAULT_REGIONS)
    unknown = [r for r in regions if resolve_region(r) is None]
    if unknown:
        raise ValueError(f"모르는 지역: {', '.join(unknown)}")
    limit = min(MAX_LIMIT, max(1, int(params.get("limit") or DEFAULT_LIMIT)))
    return Terms(budget, cash, monthly_limit, rate, years), regions, limit


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TOOL_NAME, content=[TextContent(text=text)], is_error=is_error
    )
