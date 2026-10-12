"""[core] 분양가나 보증금으로 월, 연간 원리금 상환액과 이자를 계산하고 상환액에서 금리를 역산하는 housing_loan 도구."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jarvis.core.tools.housing.fetch import FetchError
from jarvis.core.tools.registry import JarvisTool
from jarvis.model_layer.types import TextContent, ToolResultMessage

TOOL_NAME = "housing_loan"
METHODS = ("원리금균등", "원금균등", "만기일시")
MAX_YEARS = 50
# 금리 역산 범위(연 %)와 반복 수. 이분법이라 60번이면 원 단위 아래까지 맞는다
RATE_SEARCH_MAX = 100.0
RATE_SEARCH_STEPS = 60
# 연차 표가 길면 앞뒤만 보인다
YEAR_ROWS_HEAD = 5
YEAR_ROWS_TAIL = 2

# (LH 공고 id, 주택형) → (금액, 근거 글). 공고에서 분양가나 보증금을 읽어 온다
NoticePrice = Callable[[str, str], Awaitable[tuple[float, str]]]

TOOL_DESCRIPTION = (
    "주택 대출의 월, 연간 원리금 상환액과 총이자를 계산한다."
    " LH 공고는 notice_id(lh_notice 의 id)와 unit(주택형)만 주면 공고의 분양가나 임대보증금을 직접 읽어 price 로 쓴다."
    " price 에 LTV 나 자기자금을 넣어 대출원금을 정한다."
    " 상환 방식은 원리금균등, 원금균등, 만기일시. 거치기간(이자만 내는 기간)을 줄 수 있다."
    " 금리 대신 월 상환액(monthly_payment)을 주면 원리금균등 기준 연 금리를 역산한다. 금액은 원 단위."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "notice_id": {"type": "string", "description": "LH 공고 id. 주면 그 공고의 금액을 price 로 쓴다"},
        "unit": {"type": "string", "description": "notice_id 공고의 주택형. 예: 55A, 84. 비우면 첫 주택형"},
        "principal": {"type": "number", "description": "대출원금(원). 주면 price 등은 무시"},
        "price": {"type": "number", "description": "분양가나 보증금(원). ltv_percent 또는 down_payment 와 함께"},
        "ltv_percent": {"type": "number", "description": "price 중 대출 비율(%)"},
        "down_payment": {"type": "number", "description": "자기자금(원). 대출원금 = price - down_payment"},
        "annual_rate_percent": {"type": "number", "description": "연 금리(%). 예: 3.5"},
        "monthly_payment": {"type": "number", "description": "월 상환액(원). 금리를 모를 때 주면 금리를 역산"},
        "years": {"type": "integer", "description": f"대출기간(년, 거치기간 포함, 최대 {MAX_YEARS})"},
        "grace_years": {"type": "integer", "description": "거치기간(년). 기본 0"},
        "method": {"type": "string", "enum": list(METHODS), "description": "상환 방식. 기본 원리금균등"},
    },
    "required": ["years"],
}


@dataclass(frozen=True)
class Month:
    principal: float
    interest: float
    balance: float

    @property
    def payment(self) -> float:
        return self.principal + self.interest


@dataclass(frozen=True)
class Year:
    index: int
    principal: float
    interest: float
    balance: float

    @property
    def payment(self) -> float:
        return self.principal + self.interest


def annuity_payment(principal: float, monthly_rate: float, months: int) -> float:
    """원리금균등의 월 상환액. 금리 0 이면 원금을 나눈 값."""
    if months <= 0:
        return 0.0
    if monthly_rate == 0:
        return principal / months
    factor = (1 + monthly_rate) ** months
    return principal * monthly_rate * factor / (factor - 1)


def schedule(principal: float, annual_rate: float, months: int, method: str, grace_months: int = 0) -> list[Month]:
    """달마다 낸 원금, 이자, 남은 잔액. 거치 동안은 이자만 낸다."""
    rate = annual_rate / 100 / 12
    rows: list[Month] = []
    balance = principal
    for _ in range(grace_months):
        rows.append(Month(0.0, balance * rate, balance))
    repay = months - grace_months
    fixed = annuity_payment(principal, rate, repay)
    for index in range(repay):
        interest = balance * rate
        if method == "원리금균등":
            paid = fixed - interest
        elif method == "원금균등":
            paid = principal / repay
        else:
            paid = balance if index == repay - 1 else 0.0
        paid = min(paid, balance) if index < repay - 1 else balance
        balance -= paid
        rows.append(Month(paid, interest, max(balance, 0.0)))
    return rows


def yearly(rows: list[Month]) -> list[Year]:
    years = []
    for start in range(0, len(rows), 12):
        chunk = rows[start:start + 12]
        years.append(Year(
            start // 12 + 1, sum(m.principal for m in chunk), sum(m.interest for m in chunk), chunk[-1].balance
        ))
    return years


def solve_rate(principal: float, payment: float, months: int) -> float | None:
    """원리금균등 월 상환액이 payment 가 되는 연 금리(%). 원금보다 적게 갚는 값이면 None."""
    if payment * months < principal or principal <= 0:
        return None
    low, high = 0.0, RATE_SEARCH_MAX
    if annuity_payment(principal, high / 100 / 12, months) < payment:
        return None
    for _ in range(RATE_SEARCH_STEPS):
        mid = (low + high) / 2
        if annuity_payment(principal, mid / 100 / 12, months) < payment:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def resolve_principal(params: dict[str, Any]) -> tuple[float | None, str]:
    """대출원금과 그 근거. 정할 수 없으면 (None, 이유)."""
    if params.get("principal") not in (None, ""):
        return float(params["principal"]), "입력한 대출원금"
    if params.get("price") in (None, ""):
        return None, "principal 이나 price 가 필요하다"
    price = float(params["price"])
    source = f"{params['price_basis']} " if params.get("price_basis") else ""
    if params.get("ltv_percent") not in (None, ""):
        ltv = float(params["ltv_percent"])
        return price * ltv / 100, f"{source}{won(price)} × LTV {ltv:g}%"
    if params.get("down_payment") not in (None, ""):
        down = float(params["down_payment"])
        return price - down, f"{source}{won(price)} - 자기자금 {won(down)}"
    return None, "price 와 함께 ltv_percent 나 down_payment 가 필요하다"


def won(amount: float) -> str:
    """원 단위 반올림과 만원 단위 읽기. 예: 353,138,800원(약 3억 5,314만원)."""
    value = round(amount)
    man = round(value / 10_000)
    eok, rest = divmod(man, 10_000)
    reading = f"{eok}억 {rest:,}만원" if eok and rest else f"{eok}억원" if eok else f"{rest:,}만원"
    return f"{value:,}원(약 {reading})" if abs(value) >= 10_000 else f"{value:,}원"


def render(principal: float, basis: str, rate: float, years: int, grace: int, method: str, solved: bool) -> str:
    rows = schedule(principal, rate, years * 12, method, grace * 12)
    table = yearly(rows)
    interest = sum(m.interest for m in rows)
    repay_rows = rows[grace * 12:]
    rate_line = f"연 {rate:.3f}% (월 상환액에서 역산)" if solved else f"연 {rate:g}%"
    lines = [
        f"대출원금 {won(principal)} ({basis})",
        f"금리 {rate_line}, 기간 {years}년" + (f"(거치 {grace}년 포함)" if grace else "") + f", {method}",
    ]
    if grace:
        lines.append(f"거치기간 월 이자 {won(rows[0].interest)}")
    if method == "원리금균등":
        lines.append(f"월 상환액 {won(repay_rows[0].payment)} (매달 같음)")
    elif method == "원금균등":
        lines.append(f"월 상환액 첫 달 {won(repay_rows[0].payment)}, 마지막 달 {won(repay_rows[-1].payment)}")
    else:
        lines.append(f"월 이자 {won(repay_rows[0].interest)}, 만기에 원금 {won(principal)} 일시상환")
    lines.append(f"1년차 연간 상환액 {won(table[0].payment)}")
    lines.append(f"총이자 {won(interest)}, 총상환액 {won(principal + interest)}")
    lines.append(f"원금 대비 총이자 {interest / principal:.1%}")
    lines.append("\n연차 | 원금 | 이자 | 연간 상환액 | 연말 잔액")
    shown: list[Year | None] = list(table)
    if len(table) > YEAR_ROWS_HEAD + YEAR_ROWS_TAIL:
        shown = [*table[:YEAR_ROWS_HEAD], None, *table[-YEAR_ROWS_TAIL:]]
    for year in shown:
        if year is None:
            lines.append("…")
            continue
        lines.append(
            f"{year.index}년차 | {round(year.principal):,} | {round(year.interest):,} | {round(year.payment):,}"
            f" | {round(year.balance):,}"
        )
    lines.append("\n원 단위 반올림. 실제 대출은 기관의 금리 변동, 중도상환, 보증료에 따라 달라진다.")
    return "\n".join(lines)


class HousingLoanTool(JarvisTool):
    """notice_id 가 없으면 계산만 해서 같은 입력에 같은 답이다. 있으면 그 공고의 금액을 먼저 읽는다."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    def __init__(self, notice_price: NoticePrice | None = None) -> None:
        self._notice_price = notice_price

    async def execute(
        self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None
    ) -> ToolResultMessage:
        notice_id = str(params.get("notice_id") or "").strip()
        try:
            if notice_id and params.get("principal") in (None, ""):
                if self._notice_price is None:
                    raise ValueError("공고 금액을 읽을 수 없다. price 를 직접 준다")
                price, basis = await self._notice_price(notice_id, str(params.get("unit") or ""))
                params = {**params, "price": price, "price_basis": basis}
            text = calculate(params)
        except (TypeError, ValueError) as exc:
            return _result(tool_call_id, f"계산할 수 없다: {exc}", True)
        except FetchError as exc:
            return _result(tool_call_id, f"공고 금액을 읽지 못했다: {exc}", True)
        return _result(tool_call_id, text)


def calculate(params: dict[str, Any]) -> str:
    """인자를 검사하고 계산 결과 글. 틀린 입력은 ValueError."""
    principal, basis = resolve_principal(params)
    if principal is None:
        raise ValueError(basis)
    if principal <= 0:
        raise ValueError(f"대출원금이 0 이하다({basis})")
    years = int(params.get("years") or 0)
    grace = int(params.get("grace_years") or 0)
    method = str(params.get("method") or "원리금균등")
    if method not in METHODS:
        raise ValueError(f"상환 방식은 {', '.join(METHODS)} 중 하나다")
    if not 1 <= years <= MAX_YEARS or not 0 <= grace < years:
        raise ValueError(f"years 는 1~{MAX_YEARS}, grace_years 는 0 이상 years 미만이다")
    if params.get("annual_rate_percent") not in (None, ""):
        rate = float(params["annual_rate_percent"])
        if not 0 <= rate <= RATE_SEARCH_MAX:
            raise ValueError("연 금리는 0~100% 다")
        return render(principal, basis, rate, years, grace, method, solved=False)
    if params.get("monthly_payment") in (None, ""):
        raise ValueError("annual_rate_percent 나 monthly_payment 가 필요하다")
    if method != "원리금균등" or grace:
        raise ValueError("금리 역산은 거치 없는 원리금균등만 된다")
    solved = solve_rate(principal, float(params["monthly_payment"]), years * 12)
    if solved is None:
        raise ValueError("그 월 상환액으로는 기간 안에 원금을 갚을 수 없거나 금리가 100%를 넘는다")
    return render(principal, basis, solved, years, grace, method, solved=True)


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TOOL_NAME, content=[TextContent(text=text)], is_error=is_error
    )
