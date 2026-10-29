"""[core] 현금, 월 여유자금, 주거 프로필로 열린 LH, SH 공고마다 대출 경우의 수와 월 부담을 계산하는 도구."""

import re
import asyncio
from datetime import date
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, TypeVar
from collections.abc import Awaitable, Callable

from jarvis.core.tools.housing.profile import HousingProfile, ProfileStore, apply_updates, parse_pairs, regions_or_home
from jarvis.core.tools.housing.rules import NO, OK, UNKNOWN, Rules, Verdict, eligibility, load_rules, notice_access
from jarvis.core.tools.housing.fetch import Fetch, FetchBytes, FetchError, fetch_bytes, fetch_html, kst_today
from jarvis.core.tools.housing.notice_pdf import RentTerm, SaleTerm, notice_text, pdf_text, pick_notice_pdf
from jarvis.core.tools.housing.scenario import BASE, CASH_ALL, NO_LOAN, Case, Deposit, deposit_cases, fits
from jarvis.core.tools.housing.lh_notice import LhNoticeTool, Notice, build_queries, detail_url, is_sale
from jarvis.core.tools.housing.rental_complex import ComplexUnit, fetch_complexes, match_complex
from jarvis.core.tools.housing.sh_terms import ShUnit, collect, is_sh, sh_pdf_text, sh_url
from jarvis.core.tools.housing.deadline import LEAD_DAYS, track_deadlines
from jarvis.core.tools.housing.markup import deadline_label, parse_date
from jarvis.core.tools.housing.notice_pdf import rent_terms, sale_terms
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.housing.lh_notice import resolve_region
from jarvis.core.tools.registry import JarvisTool, ToolContext
from jarvis.core.tools.housing.scenario import purchase_cases
from jarvis.core.tools.housing.rules import unit_mismatch
from jarvis.core.tools.housing.amount import parse_won
from jarvis.memory.scope import LOCAL_USER

if TYPE_CHECKING:
    from jarvis.agent_layer.openloop.store import OpenLoopStore

TOOL_NAME = "housing_budget"
T = TypeVar("T")
DEFAULT_LIMIT = 3
MAX_LIMIT = 10
# ponytail: 상세를 공고 100건까지만 연다(전국 공고중이 80건 안팎), 열린 공고가 더 늘면 지역이나 유형으로 나눠 부른다
MAX_DETAILS = 100
# ponytail: 공고문 PDF 는 한 번에 60건까지만 받는다(건당 1MB 안팎, 수 초), 더 필요하면 지역을 나눠 부른다
MAX_PDFS = 60
# 금액을 찾지 못한 공고는 이만큼만 이름을 적고 나머지는 수만 센다
MAX_UNKNOWN_LISTED = 10
# 게시판과 공고문 서버에 동시에 거는 요청 수. 순서대로 열면 전국 조회가 몇 분 걸린다
CONCURRENCY = 4
OPEN_STATUS = "공고중"
INCREASE, DECREASE = "보증금 증액 전환", "보증금 감액 전환"
# 신청 가능성이 높은 공고부터 보인다. 가능성이 낮아도 빼지 않고 뒤로 보낸다
ACCESS_ORDER = {OK: 0, UNKNOWN: 1, NO: 2}
ACCESS_LABEL = {OK: "높음", UNKNOWN: "확인 필요", NO: "낮음"}
# 추천 1순위를 고르는 묶음. 분양과 임대는 월 부담의 뜻이 달라 따로 고른다
PICK_GROUPS = (("분양", True), ("임대", False))
UNSURE_NOTE = "자격은 공고문 확인이 필요해요"
# 1순위만 볼 때 현금을 모르면 이 항목 줄을 준다. 모델에게 짓게 하면 키 없이 말만 써 아무것도 알리지 못했다(실측)
ASK_MONEY_ITEM = (
    "항목: [ask-money] 추천 공고를 찾으려면 보유 현금과 월 여유자금이 필요해요. 알려 주시면 그때부터 챙길게요."
)

TOOL_DESCRIPTION = (
    "보유 현금과 월 여유자금(월 부담 상한)으로 지금 공고중인 LH 공고(지역에 서울이 있으면 SH 모집 공고도)마다"
    " 대출 경우의 수를 계산해 추천한다."
    " 분양은 구입 대출(디딤돌, 보금자리론, 시중 주담대)을, 임대는 보증금 대출(버팀목, 청년 버팀목, 시중 전세대출)과"
    " 공고문의 보증금 증액, 감액 전환을 펼친다. 대출 한도는 상품 한도, LTV, 규제 한도, DSR/DTI 중 가장 작은 값이고,"
    " 금리는 조사한 범위(하단~상단)로 월 이자와 원금 상환을 계산한다."
    " 현금을 다 넣는 경우와 대출을 최대로 쓰는 경우를 같이 보인다."
    " 자격은 사용자의 주거 프로필(무주택, 생애최초, 혼인, 소득, 나이, 가구원수, 수급자, 대학생)로 가린다."
    " 프로필은 housing_profile 로 보고 고친다."
    " 결과 글은 고치지 않고 그대로 사용자 답이 되니, 프로필을 고칠 일이 있으면 먼저 끝내고 이 도구는 혼자 부른다."
    " '현금 1억 5천, 월 200만원으로 맞는 공고' 같은 요청에 쓴다. 금액은 숫자(원)나 사용자가 말한 그대로('1억 5천')."
)
_AMOUNT = "원 단위 숫자나 사용자가 말한 그대로의 금액 글. 예: 150000000, '1억 5천', '200만원'"
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cash": {"type": "string", "description": f"보유 현금. 비우면 주거 프로필의 현금. {_AMOUNT}"},
        "monthly_limit": {
            "type": "string",
            "description": f"월 여유자금(대출 상환 + 월임대료 상한). 비우면 주거 프로필의 값. {_AMOUNT}",
        },
        "budget": {"type": "string", "description": f"총액 상한(분양가나 보증금). 사용자가 말했을 때만. {_AMOUNT}"},
        "regions": {"type": "string", "description": "지역. 쉼표로 여럿. 예: 서울,경기. 비우면 관심 지역(없으면 전국)"},
        "annual_rate_percent": {"type": "number", "description": "사용자가 금리를 정했을 때만. 비우면 상품별 범위"},
        "years": {"type": "integer", "description": "분양 대출 기간(년). 비우면 상품 기본(30년)"},
        "conditions": {
            "type": "string",
            "description": "이번 계산에만 쓸 프로필 조건. 예: '연소득=7000만, 혼인=기혼'. 저장하려면 housing_profile",
        },
        "limit": {"type": "integer", "description": f"분양, 임대 각각 추천 수(기본 {DEFAULT_LIMIT}, 최대 {MAX_LIMIT})"},
        "picks_only": {
            "type": "boolean",
            "description": "추천 1순위 줄만 받는다(목표 차례처럼 1순위만 볼 때). 전체 글은 1만 토큰이 넘는다",
        },
    },
}


@dataclass(frozen=True)
class Option:
    """공고의 주택형 하나와 그 금액. sale 이면 분양가, 아니면 임대보증금. more, less 는 최대 전환 조건."""

    unit: str
    price: int
    rent: int
    sale: bool
    source: str
    more: tuple[int, int] | None = None
    less: tuple[int, int] | None = None

    def deposits(self) -> list[Deposit]:
        items = [Deposit(BASE, self.price, self.rent)]
        if self.more:
            items.append(Deposit(INCREASE, *self.more))
        if self.less:
            items.append(Deposit(DECREASE, *self.less))
        return items


@dataclass(frozen=True)
class Plan:
    """공고 하나의 추천: 가장 싼 맞는 경우가 나온 주택형과 그 주택형의 모든 경우."""

    notice: Notice
    option: Option
    cases: tuple[Case, ...]
    best: Case
    fitted: bool = True  # best 가 조건에 맞는 경우인가(아니면 가장 가까운 경우)
    fits: int = 1  # 맞는 경우가 있는 주택형 수
    units: int = 1  # 금액을 아는 주택형 수
    access: Verdict = Verdict(UNKNOWN)  # 공고 유형으로 본 신청 가능성


@dataclass(frozen=True)
class Terms:
    cash: float
    monthly_limit: float | None
    budget: float | None
    rate: float | None
    years: int | None


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
    return [Option(t.unit, t.deposit, t.rent, False, "공고문 PDF 임대조건", t.more, t.less) for t in terms]


def options_from_sale(terms: list[SaleTerm]) -> list[Option]:
    """층별 가격 중 최고가로 계산한다(비싼 쪽으로 봐야 모자람을 놓치지 않는다)."""
    options = []
    for t in terms:
        source = "공고문 PDF 분양가"
        if t.low != t.high:
            source += f", 층별 {man(t.low)}~{man(t.high)} 중 최고가"
        if t.loan:
            source += f", 공고문 융자금(주택도시기금) {man(t.loan)} 포함(승계, 대환 조건은 공고문)"
        options.append(Option(t.unit, t.high, 0, True, source))
    return options


def options_from_complex(rows: list[ComplexUnit]) -> list[Option]:
    return [
        Option(f"{r.name} {r.area:g}㎡", r.deposit, r.rent, False, "임대주택검색 단지 금액")
        for r in rows
    ]


def plan_for(notice: Notice, options: list[Option], terms: Terms, rules: Rules, profile: HousingProfile,
             today: date) -> Plan | None:
    """주택형마다 경우를 펼쳐, 맞는 경우의 월 부담(금리 상단)이 가장 작은 주택형.

    맞는 경우가 없으면 가장 가까운 경우(현금 부족이 작고, 그다음 월 부담이 작은)의 주택형.
    계산할 주택형이 없으면 None.
    """
    sale = options[0].sale
    products = [p for p in rules.products if p.purpose == ("purchase" if sale else "deposit")
                and eligibility(p, profile, today).status != NO]
    area = rules.area(notice.region, notice.title)
    best: Plan | None = None
    fitting = 0
    for option in options:
        if unit_mismatch(rules, option.unit, profile, today) is not None:
            continue
        if terms.budget is not None and option.price > terms.budget:
            continue
        if option.sale:
            cases = purchase_cases(option.price, area, products, rules, profile, today, terms.cash, terms.years,
                                   terms.rate)
            if option.rent:
                # 토지임대부 분양은 대출 상환과 함께 월 토지임대료를 낸다
                cases = [replace(c, rent=option.rent) for c in cases]
        else:
            cases = deposit_cases(option.deposits(), area, products, rules, profile, today, terms.cash, terms.rate)
        good = [c for c in cases if fits(c, terms.monthly_limit)]
        fitting += bool(good)
        live = [c for c in cases if c.verdict.status != NO]
        if not live:
            continue
        top = min(good, key=lambda c: c.monthly) if good else min(live, key=_distance)
        candidate = Plan(notice, option, tuple(cases), top, fitted=bool(good))
        if best is None or _rank(candidate) < _rank(best):
            best = candidate
    if best is None:
        return None
    access = notice_access(rules, notice.kind, notice.title, profile)
    return replace(best, fits=fitting, units=len(options), access=access)


def _distance(case: Case) -> tuple[float, float]:
    return case.shortfall, case.monthly


def _rank(plan: Plan) -> tuple[int, bool, float, float]:
    """신청 가능성이 높은 공고가 먼저. 그 안에서 맞는 공고를 월 부담 순, 안 맞는 공고는 모자람이 작은 순."""
    access = ACCESS_ORDER[plan.access.status]
    if plan.fitted:
        return access, False, plan.best.monthly, 0.0
    return access, True, *_distance(plan.best)


def top_pick(plans: list[Plan]) -> Plan | None:
    """한 묶음(분양 또는 임대)에서 하나를 고른다. 맞는 경우가 있고 신청 가능성이 낮지 않은 공고 중
    가능성이 높은 것, 그다음 월 부담이 작은 것, 같으면 마감이 이른 것. 고를 것이 없으면 None. 순수 함수.

    분양과 임대는 월 부담의 뜻이 달라(원금 상환과 임대료) 서로 견주지 않는다.
    """
    live = [p for p in plans if p.fitted and p.access.status != NO]
    return min(live, key=lambda p: (_rank(p), p.notice.closes or "9999")) if live else None


def notice_url(notice: Notice) -> str:
    return sh_url(notice) if is_sh(notice.id) else detail_url(notice.id)


def options_from_sh(units: list[ShUnit], notice: Notice, rules: Rules) -> list[Option]:
    """SH 공고문에서 읽은 금액. 제목의 공급대상 말(신혼, 청년, 대학생)을 주택형에 붙여 프로필과 어긋나면 빼게 한다."""
    words = [t["word"] for t in rules.notice_kinds.get("unit_targets", ()) if t["word"] in notice.title]
    options = []
    for u in units:
        unit = " ".join([u.unit, *words])
        if u.sale:
            source = "SH 공고문 PDF 분양가"
            if u.low < u.price:
                source += f", 동호별 {man(u.low)}~{man(u.price)} 중 최고가"
            if u.rent:
                source += f", 토지임대부라 월 토지임대료 {u.rent:,}원을 월 부담에 더했다"
        else:
            source = "SH 공고문 PDF 임대조건(소득 구간이 나뉘면 높은 구간)"
        options.append(Option(unit, u.price, u.rent, u.sale, source))
    return options


def pick_line(title: str, plan: Plan | None, terms: Terms) -> str:
    if plan is None:
        return f"추천 1순위({title}): 없음. 맞는 경우가 있으면서 신청 가능성이 낮지 않은 공고가 없다"
    n, case = plan.notice, plan.best
    room = (
        f", 월 여유 {man(terms.monthly_limit - case.monthly)} 남음" if terms.monthly_limit is not None else ""
    )
    return (
        f"추천 1순위({title}): {n.title} | 신청 가능성 {ACCESS_LABEL[plan.access.status]}"
        f" | {plan.option.unit} 월 부담 최대 {man(case.monthly)}{room} | 마감 {n.closes or '미상'}"
        # 링크의 공고 id 는 다음에도 바뀌지 않는다. 목표 차례가 이미 알린 공고인지 이것으로 가린다
        f" | {notice_url(n)}"
    )


def man(amount: float) -> str:
    """만원 단위 읽기. 예: 2억 7,000만원, 9,280만원, 0원."""
    value = round(amount / 10_000)
    if value == 0:
        return "0원" if round(amount) == 0 else f"{round(amount):,}원"
    eok, rest = divmod(abs(value), 10_000)
    sign = "-" if value < 0 else ""
    if eok and rest:
        return f"{sign}{eok}억 {rest:,}만원"
    return f"{sign}{eok}억원" if eok else f"{sign}{rest:,}만원"


def _span(low: float, high: float, unit: str = "원") -> str:
    a, b = round(low), round(high)
    return f"{a:,}{unit}" if a == b else f"{a:,}~{b:,}{unit}"


def _rate(case: Case) -> str:
    low, high = case.rate
    return f"연 {low:g}%" if low == high else f"연 {low:g}~{high:g}%"


def _area_label(case: Case, expanded: bool) -> str:
    if not expanded:
        return ""
    return "규제지역이면 | " if case.area.regulated else "비규제지역이면 | "


def _case_line(case: Case, terms: Terms) -> str:
    """경우 하나. 맞음 여부와 막힌 이유를 끝에 붙인다."""
    if case.verdict.status == NO:
        return f"불가({', '.join(case.verdict.reasons)})"
    if case.cash_case == NO_LOAN:
        body = f"현금으로 보증금 {man(case.price)}: 대출 없음 → 월 {case.rent:,}원(월임대료)"
    elif case.years is None:
        body = (
            f"대출 {man(case.loan)}, 현금 {man(case.cash_used)} → 월 이자 {_span(*case.pay)}"
            + (f" + 월임대료 {case.rent:,}원 = {_span(case.monthly_low, case.monthly)}" if case.rent else "")
            + f", 만기에 원금 {man(case.loan)} 일시상환"
        )
    else:
        principal = case.pay[1] - case.first_interest
        kept = terms.cash - case.cash_used
        body = (
            f"{case.cash_case} 대출 {man(case.loan)}, 현금 {man(case.cash_used)} 투입"
            + (f"({man(kept)} 남김)" if case.cash_case != CASH_ALL and kept > 0 else "")
            + f" → 월 {_span(*case.pay)} = 이자 {round(case.first_interest):,}원 + 원금 {round(principal):,}원"
            "(금리 상단, 첫 달)"
            + (f" + 월 토지임대료 {case.rent:,}원 = {_span(case.monthly_low, case.monthly)}" if case.rent else "")
        )
    problems = []
    if case.shortfall > 0:
        problems.append(f"현금 부족 {man(case.shortfall)}")
    if terms.monthly_limit is not None and case.monthly > terms.monthly_limit:
        problems.append("월 여유자금 초과")
    marks = ["맞음" if not problems else "안 맞음", *problems]
    if case.verdict.status == UNKNOWN:
        marks.append(f"자격 확인: {', '.join(case.verdict.reasons)}")
    return f"{body} [{'; '.join(marks)}]"


def _limit_text(case: Case) -> str:
    if case.limit is None:
        return ""
    parts = ", ".join(f"{name} {man(value)}" for name, value in case.limit.parts)
    notes = f". {' '.join(case.limit.notes)}" if case.limit.notes else ""
    return f"한도 {man(case.limit.amount)} = 최소({parts}){notes}"


def render_plan(index: int, plan: Plan, terms: Terms, today: date) -> list[str]:
    n, o = plan.notice, plan.option
    label = deadline_label(parse_date(n.closes), today)
    kind = "분양가" if o.sale else "보증금"
    rent = f", {'월 토지임대료' if o.sale else '월임대료'} {o.rent:,}원" if o.rent else ""
    expanded = len({c.area.regulated for c in plan.cases}) > 1
    region_note = "수도권" if plan.best.area.capital else "비수도권"
    if expanded:
        region_note += ", 규제지역인지 몰라 두 경우"
    elif plan.best.area.regulated:
        region_note += ", 규제지역"
    lines = [
        f"{index}. [{label}] {n.title}",
        f"   {n.kind} | {n.region} | 마감 {n.closes or '미상'} | id {n.id} | {region_note}",
        f"   {o.unit} {kind} {man(o.price)}{rent} ({o.source})",
        f"   신청 가능성 {ACCESS_LABEL[plan.access.status]}: {'; '.join(plan.access.reasons)}",
        f"   맞는 경우가 있는 주택형 {plan.fits}/{plan.units}개. "
        + ("이 주택형이 월 부담이 가장 작다" if plan.fitted else "맞는 경우가 없어 가장 가까운 주택형을 보인다"),
    ]
    groups: dict[tuple[Any, ...], list[Case]] = {}
    for case in plan.cases:
        key = (case.variant, case.product.id if case.product else "", case.area.regulated)
        groups.setdefault(key, []).append(case)
    for (variant, _, _), cases in groups.items():
        first = cases[0]
        head = []
        if not o.sale and variant != BASE:
            head.append(f"{variant}(보증금 {man(first.price)}, 월임대료 {first.rent:,}원)")
        if first.product is not None:
            head.append(_area_label(first, expanded) + first.product.name)
            if first.verdict.status != NO:
                term = f"{first.years}년 원리금균등" if first.years else "만기일시(이자만)"
                note = f"({first.years_note})" if first.years_note else ""
                head.append(f"{_rate(first)} {term}{note}")
        # 한 상품의 경우를 한 줄에 모은다. 줄이 갈리면 모델이 답을 옮기며 경우 줄을 떨어뜨린다
        limit = f" ({_limit_text(first)})" if first.limit is not None and first.verdict.status != NO else ""
        cases_text = " / ".join(_case_line(c, terms) for c in cases)
        lines.append(f"   · {' '.join(head) or '기본 조건'}: {cases_text}{limit}")
    lines.append(f"   {notice_url(n)}")
    return lines


def render(
    terms: Terms, regions: list[str], plans: list[Plan], over: list[Notice], unknown: list[Notice],
    skipped: int, limit: int, today: date, rules: Rules, profile: HousingProfile, profile_note: str,
    sh_note: str = "",
) -> str:
    cap = f", 월 여유자금 {man(terms.monthly_limit)}" if terms.monthly_limit is not None else ""
    budget = f", 총액 상한 {man(terms.budget)}" if terms.budget is not None else ""
    fit_sale = sum(p.fitted for p in plans if p.option.sale)
    fit_rent = sum(p.fitted for p in plans if not p.option.sale)
    with_sh = any(is_sh(n.id) for n in [*(p.notice for p in plans), *over, *unknown])
    lines = [
        # 이 글은 고치지 않고 그대로 답이 된다. KAREN 의 말로 결론을 먼저 둔다
        f"애쉬, {', '.join(regions)}에서 이 조건에 맞는 공고는 분양 {fit_sale}건, 임대 {fit_rent}건이에요."
        + (" 아래 추천 1순위부터 보시면 돼요." if fit_sale or fit_rent else " 가장 가까운 공고를 아래에 정리했어요."),
        f"{'LH, SH' if with_sh else 'LH'} 공고 대출 경우의 수"
        f" ({', '.join(regions)} | 현금 {terms.cash:,.0f}원({man(terms.cash)}){cap}{budget})",
        f"프로필: {', '.join(profile.lines(today))} ({profile_note})",
    ]
    blocked = []
    unsure = []
    for product in rules.products:
        verdict = eligibility(product, profile, today)
        if verdict.status == NO:
            blocked.append(f"{product.name}({', '.join(verdict.reasons)})")
        elif verdict.status == UNKNOWN:
            unsure.append(f"{product.name}({', '.join(verdict.reasons)})")
    if blocked:
        lines.append("프로필로 자격이 안 되어 뺀 상품: " + "; ".join(blocked))
    if unsure:
        lines.append(
            "프로필에 없어 자격을 확정하지 못한 상품(계산은 했다): " + "; ".join(unsure)
            + ". 무주택, 생애최초, 혼인, 연소득, 나이, 가구원수를 알려 주면 자격을 가려 다시 계산한다"
        )
    rate = f"사용자가 준 연 {terms.rate:g}%" if terms.rate is not None else "상품별 조사 범위(하단~상단)"
    lines.append(
        f"가정: 금리는 {rate}. 맞음 여부는 금리 상단으로 본다."
        " 분양은 입주 때 잔금 대출 기준(계약금, 중도금 일정은 단지별)."
        f" 다른 대출은 없다고 보고 DSR/DTI 를 셌다. 마감은 KST {today.isoformat()} 기준"
    )
    stale = " 오래됐으니 금리와 규제를 은행, 기금 사이트에서 다시 확인한다." if rules.stale(today) else ""
    lines.append(f"대출 규칙 기준일 {rules.checked.isoformat()}(loan_rules.yaml).{stale}")
    if sh_note:
        lines.append(sh_note)
    # 하나를 물으면 이 줄로 답한다. 목록 위에 둬야 모델이 옮기며 떨어뜨리지 않는다
    for title, sale in PICK_GROUPS:
        lines.append(pick_line(title, top_pick([p for p in plans if p.option.sale is sale]), terms))
    for title, sale in (("분양(구입 대출)", True), ("임대(보증금 대출)", False)):
        group = sorted((p for p in plans if p.option.sale is sale), key=_rank)
        fitted = sum(p.fitted for p in group)
        shown = f", {min(len(group), limit)}건 표시(맞는 공고가 모자라면 가장 가까운 공고로 채운다)" if group else ""
        lines.append(f"\n[{title}] 금액을 아는 공고 {len(group)}건 중 맞는 경우가 있는 공고 {fitted}건{shown}")
        # 머리 바로 아래에 둔다. 묶음 끝에 두면 모델이 답을 옮기며 떨어뜨린다
        unlikely: dict[str, list[str]] = {}
        for p in group[limit:]:
            if p.fitted and p.access.status == NO:
                unlikely.setdefault(p.access.reasons[0], []).append(p.notice.title)
        for reason, titles in unlikely.items():
            more = f" 외 {len(titles) - 3}건" if len(titles) > 3 else ""
            lines.append(
                f"   맞는 경우는 있지만 신청 가능성이 낮아 뒤로 보낸 공고 {len(titles)}건({reason}): "
                + ", ".join(titles[:3]) + more
            )
        for index, plan in enumerate(group[:limit], 1):
            lines += render_plan(index, plan, terms, today)
        rest = [p.notice.title for p in group[limit:] if not p.fitted]
        if rest:
            lines.append(f"   맞는 경우가 없는 다른 공고 {len(rest)}건: " + ", ".join(rest[:5]))
    if over:
        names = ", ".join(n.title for n in over[:5])
        lines.append(f"\n프로필이나 총액 상한으로 계산할 주택형이 없는 공고 {len(over)}건: {names}")
    if unknown:
        lines.append(f"\n금액을 찾지 못한 공고 {len(unknown)}건(상세, 공고문 PDF, 임대주택검색에 금액 없음. 첨부 확인)")
        lines += [
            f"- [{deadline_label(parse_date(n.closes), today)}] {n.title} | {notice_url(n)}"
            for n in unknown[:MAX_UNKNOWN_LISTED]
        ]
        if len(unknown) > MAX_UNKNOWN_LISTED:
            lines.append(f"- 그 밖에 {len(unknown) - MAX_UNKNOWN_LISTED}건(LH 공고 목록에서 볼 수 있다)")
    if skipped:
        lines.append(
            f"\n상세를 {MAX_DETAILS}건까지만 열어 {skipped}건은 보지 않았다. 지역을 나눠 다시 물으면 나머지를 본다."
        )
    used = [p for p in rules.products if any(c.product is p for plan in plans for c in plan.cases)]
    if used:
        lines.append("\n출처: " + "; ".join(f"{p.name} {p.get('source')}" for p in used))
    lines.append(
        "\n이 계산은 정해진 답이 아니라 고를 수 있는 경우의 수다."
        " 신청 가능성은 프로필, 1인 가구 소득 기준, 공고 제목과 주택형 이름으로 본 가늠이라"
        " 공고문의 소득, 자산 기준과 공급대상을 신청 전에 확인한다."
        " 매입임대와 전세임대는 집마다 금액이 달라 공고문 확인 목록에 남는다."
        " SH 공고는 단지마다 표가 달라 공고문 PDF 에서 줄 단위로 읽은 금액이니 공고문으로 확인한다."
    )
    return "\n".join(lines)


class HousingBudgetTool(JarvisTool):
    """읽기와 계산만 한다. 같은 날 같은 인자면 같은 답이다(게시판이 바뀌지 않는 한)."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"
    # 사람이 없을 때는 주거 프로필의 현금, 월 여유자금으로만 계산한다. 목표 차례에서 모델이 현금을 지어낸 적이 있다
    user_only_params = ("cash", "monthly_limit", "budget", "conditions", "annual_rate_percent", "years")

    def __init__(
        self,
        notices: LhNoticeTool,
        fetch: Fetch | None = None,
        today: Callable[[], date] = kst_today,
        fetch_file: FetchBytes | None = None,
        read_pdf: Callable[[bytes], str] = pdf_text,
        profiles: ProfileStore | None = None,
        rules: Callable[[], Rules] = load_rules,
        loops: "OpenLoopStore | None" = None,
        sh_fetch: Fetch | None = None,
        read_sh_pdf: Callable[[bytes], str] = sh_pdf_text,
    ) -> None:
        self._notices = notices
        # SH 게시판. 없으면 SH 공고를 보지 않는다
        self._sh_fetch = sh_fetch
        self._read_sh_pdf = read_sh_pdf
        # 추천 1순위의 마감 전 약속을 남길 곳. 없으면 남기지 않는다
        self._loops = loops
        self._fetch = fetch or fetch_html
        self._fetch_file = fetch_file or fetch_bytes
        self._read_pdf = read_pdf
        self._today = today
        self._profiles = profiles
        self._rules = rules

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        today = self._today()
        try:
            profile, note = await self._profile(context, str(params.get("conditions") or ""), today)
            terms, regions, limit = parse_terms(params, profile)
        except MissingCash as exc:
            if params.get("picks_only"):
                return _result(tool_call_id, f"{exc}\n{ASK_MONEY_ITEM}")
            return _result(tool_call_id, f"조건을 읽을 수 없다: {exc}", True)
        except (TypeError, ValueError) as exc:
            return _result(tool_call_id, f"조건을 읽을 수 없다: {exc}", True)
        try:
            text, picks = await self._recommend(terms, regions, limit, profile, note, today)
        except (FetchError, ValueError) as exc:
            return _result(tool_call_id, f"LH 조회 실패: {exc}", True)
        if params.get("picks_only"):
            text = picks_text(text, picks)
        notices = [p.notice for p in picks.values() if p is not None]
        return _result(tool_call_id, text + await self._track(notices, context, today), final=True)

    async def _track(self, picks: list[Notice], context: ToolContext | None, today: date) -> str:
        """추천 1순위의 마감 전 약속을 남기고, 새로 남겼으면 다시 알리겠다는 한 줄을 돌려준다."""
        scope = getattr(context, "scope", None)
        session_id = getattr(context, "session_id", None)
        if self._loops is None or scope is None or not session_id or not picks:
            return ""
        added = await track_deadlines(self._loops, picks, session_id, scope.agent_id, today)
        if not added:
            return ""
        names = ", ".join(n.title for n in added)
        return f"\n추천 1순위({names})는 마감 {LEAD_DAYS}일 전 아침에 다시 알려 드릴게요."

    async def _profile(self, context: ToolContext | None, conditions: str, today: date) -> tuple[HousingProfile, str]:
        """저장된 프로필에 이번 조건을 얹는다. 저장은 하지 않는다."""
        scope = getattr(context, "scope", None)
        profile = HousingProfile()
        note = "저장된 프로필 없음. 모르는 조건은 자격 확인으로 남긴다"
        if self._profiles is not None and scope is not None:
            profile = await self._profiles.get(scope.user_id or LOCAL_USER)
            if not profile.is_empty():
                note = "저장된 프로필. /housing 이나 말로 알려 주면 바꾼다"
        if conditions.strip():
            profile = apply_updates(profile, parse_pairs(conditions), today)
            note += ". 이번 계산에만 조건을 덧씌움: " + conditions.strip()
        return profile, note

    async def _recommend(self, terms: Terms, regions: list[str], limit: int, profile: HousingProfile, note: str,
                         today: date) -> tuple[str, dict[str, Plan | None]]:
        rules = self._rules()
        # SH 는 서울 공고뿐이다. LH 를 찾는 동안 함께 받는다
        seoul = any(r.startswith("서울") or r == "전국" for r in regions)
        sh_job = (
            asyncio.create_task(collect(self._sh_fetch, self._fetch_file, self._read_sh_pdf, today))
            if self._sh_fetch is not None and seoul else None
        )
        try:
            return await self._recommend_with(terms, regions, limit, profile, note, today, rules, sh_job)
        finally:
            # LH 조회가 실패해 SH 결과를 쓰지 않을 때도 일을 남기지 않는다(끝난 일의 예외도 거둔다)
            if sh_job is not None and not sh_job.done():
                sh_job.cancel()
            elif sh_job is not None and not sh_job.cancelled():
                sh_job.exception()

    async def _recommend_with(
        self, terms: Terms, regions: list[str], limit: int, profile: HousingProfile, note: str, today: date,
        rules: Rules, sh_job: "asyncio.Task[list[tuple[Notice, list[ShUnit]]]] | None",
    ) -> tuple[str, dict[str, Plan | None]]:
        notices: dict[str, Notice] = {}
        for region in regions:
            queries, reason = build_queries({"region": region, "status": OPEN_STATUS})
            if reason is not None:
                raise ValueError(reason)
            for _, _, found in await self._notices.search([replace(q, all_pages=True) for q in queries], today):
                for n in found:
                    close = parse_date(n.closes)
                    if close is None or close >= today:
                        notices.setdefault(n.id, n)
        ordered = sorted(notices.values(), key=lambda n: parse_date(n.closes) or date.max)
        targets = ordered[:MAX_DETAILS]
        gate = asyncio.Semaphore(CONCURRENCY)
        details = await asyncio.gather(*(_bounded(gate, self._notices.detail(n.id)) for n in targets))
        priced = [options_from_units(d["units"]) for d in details]
        # 상세에 금액이 없는 공고만 공고문을 받는다. 분양 공고가 먼저다(임대는 단지 금액으로 한 번 더 찾는다).
        # 어느 공고를 받을지는 (분양 먼저, 마감순)으로 미리 정해 결과가 매번 같다
        pdf_ids = [None if priced[i] else pick_notice_pdf(d["file_ids"]) for i, d in enumerate(details)]
        need = [(i, pdf) for i, pdf in enumerate(pdf_ids) if pdf is not None]
        need = sorted(need, key=lambda item: not is_sale(targets[item[0]].id))[:MAX_PDFS]
        parsed = await asyncio.gather(*(_bounded(gate, self._pdf_options(pdf, targets[i])) for i, pdf in need))
        for (i, _), pdf_options in zip(need, parsed, strict=True):
            priced[i] = pdf_options
        complexes: dict[str, list[ComplexUnit]] = {}
        plans, over, unknown = [], [], []
        for notice, options in zip(targets, priced, strict=True):
            if not options:
                options = options_from_complex(await self._complex_rows(notice, complexes))
            if not options:
                unknown.append(notice)
                continue
            plan = plan_for(notice, options, terms, rules, profile, today)
            if plan is None:
                over.append(notice)
            else:
                plans.append(plan)
        sh_note = ""
        if sh_job is not None:
            try:
                sh_found = await sh_job
            except (FetchError, ValueError) as exc:
                sh_found, sh_note = [], f"SH 공고는 보지 못했다: {exc}"
            opened = [(n, units) for n, units in sh_found if (parse_date(n.closes) or today) >= today]
            for notice, units in opened:
                options = options_from_sh(units, notice, rules)
                plan = plan_for(notice, options, terms, rules, profile, today) if options else None
                if not options:
                    unknown.append(notice)
                elif plan is None:
                    over.append(notice)
                else:
                    plans.append(plan)
            if sh_found:
                sh_note = (
                    f"SH(서울) 모집 공고 {len(opened)}건 중 공고문 PDF 에서 금액을 읽은 공고"
                    f" {sum(bool(u) for _, u in opened)}건. SH 마감은 게시글의 접수 기간으로 짐작했다"
                )
        skipped = max(0, len(ordered) - MAX_DETAILS)
        picks = {title: top_pick([p for p in plans if p.option.sale is sale]) for title, sale in PICK_GROUPS}
        text = render(terms, regions, plans, over, unknown, skipped, limit, today, rules, profile, note, sh_note)
        return text, picks

    async def _pdf_options(self, file_id: str, notice: Notice) -> list[Option]:
        """공고문의 분양가 표나 임대조건 표. 못 받거나 못 읽으면 빈 목록. 한 공고의 실패로 추천 전체를 멈추지 않는다."""
        try:
            text = await notice_text(self._fetch_file, file_id, notice_url(notice), self._read_pdf)
        except Exception:  # FetchError, 깨진 PDF(pypdf 의 여러 예외)
            return []
        if is_sale(notice.id):
            return options_from_sale(sale_terms(text))
        return options_from_terms(rent_terms(text))

    async def _complex_rows(self, notice: Notice, cache: dict[str, list[ComplexUnit]]) -> list[ComplexUnit]:
        """공고 지역의 임대 단지 전체를 한 번만 받아 공고 제목으로 단지를 고른다."""
        code = resolve_region(notice.region.split(" 외")[0])
        if not code:
            return []
        if code not in cache:
            cache[code] = await fetch_complexes(self._fetch, code)
        return match_complex(notice.title, notice.kind, cache[code])


async def _bounded(gate: asyncio.Semaphore, work: Awaitable[T]) -> T:
    async with gate:
        return await work


def pick_item(title: str, plan: Plan | None) -> str:
    """목표 차례가 그대로 옮길 1순위 한 줄. 키(공고 id), 공고명, 주택형 월 부담, 마감, 링크. 순수 함수.

    모델에게 이 줄을 짓게 하면 링크를 줄이고 '확인 필요' 말을 빠뜨렸다(실측). 코드가 짓고 모델은 옮긴다.
    """
    if plan is None:
        return f"추천 1순위({title}): 없음"
    n, case = plan.notice, plan.best
    unsure = f" {UNSURE_NOTE}" if plan.access.status == UNKNOWN else ""
    # 사용자는 대출을 받는 방향으로 본다. 어떤 대출을 얼마나 쓰는지 없으면 월 부담만으로는 고를 수 없다
    loan = (f"{case.product.name} {man(case.loan)} + 현금 {man(case.cash_used)}" if case.product is not None
            else f"대출 없이 현금 {man(case.price)}")
    return (
        f"추천 1순위({title}) 항목: [{n.id}] {n.title}, {plan.option.unit} {loan}, 월 부담 최대 {man(case.monthly)},"
        f" 마감 {n.closes or '미상'}, {notice_url(n)}{unsure}"
    )


def picks_text(text: str, picks: dict[str, Plan | None]) -> str:
    """전체 추천 글 대신 첫 줄(결론), 계산 조건 줄, 1순위 항목 줄만. 목표 차례의 입력 토큰이 18k 에서 10k 로 준다."""
    return "\n".join([*text.splitlines()[:2], *(pick_item(title, plan) for title, plan in picks.items())])


def _amount(params: dict[str, Any], key: str) -> float | None:
    value = params.get(key)
    if value in (None, "", 0, "0"):
        return None
    return float(parse_won(value))


class MissingCash(ValueError):
    """보유 현금이 인자에도 프로필에도 없다. 사용자에게 물어야 하는 경우라 다른 입력 오류와 가른다."""


def parse_terms(params: dict[str, Any], profile: HousingProfile | None = None) -> tuple[Terms, list[str], int]:
    """인자를 검사한 계산 조건, 지역 목록(비우면 프로필의 관심 지역), 추천 수. 틀리면 ValueError."""
    saved = profile or HousingProfile()
    # 현금 0 은 "현금 없음"이라는 값이다. 비운 것만 프로필에서 읽는다
    raw_cash = params.get("cash")
    cash = float(parse_won(raw_cash)) if raw_cash not in (None, "") else None
    if cash is None:
        if saved.cash is None:
            raise MissingCash("보유 현금(cash)을 모른다. 사용자에게 묻거나 housing_profile 에 저장된 값이 있어야 한다")
        cash = float(saved.cash)
    monthly_limit = _amount(params, "monthly_limit")
    if monthly_limit is None and saved.monthly_limit is not None:
        monthly_limit = float(saved.monthly_limit)
    budget = _amount(params, "budget")
    if cash < 0 or (budget is not None and budget <= 0):
        raise ValueError("cash 는 0 이상, budget 은 0 보다 크다")
    rate_value = params.get("annual_rate_percent")
    rate = float(rate_value) if rate_value not in (None, "") else None
    years_value = params.get("years")
    years = int(years_value) if years_value not in (None, "", 0) else None
    if (rate is not None and not 0 <= rate <= 100) or (years is not None and not 1 <= years <= 50):
        raise ValueError("금리는 0~100%, 기간은 1~50년이다")
    regions = regions_or_home(params.get("regions"), profile or HousingProfile())
    unknown = [r for r in regions if resolve_region(r) is None]
    if unknown:
        raise ValueError(f"모르는 지역: {', '.join(unknown)}")
    limit = min(MAX_LIMIT, max(1, int(params.get("limit") or DEFAULT_LIMIT)))
    return Terms(cash, monthly_limit, budget, rate, years), regions, limit


def _result(tool_call_id: str, text: str, is_error: bool = False, final: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TOOL_NAME, content=[TextContent(text=text)], is_error=is_error,
        final=final,
    )
