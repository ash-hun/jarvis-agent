"""[core] 주택형 하나를 대출 상품, 규제지역 여부, 보증금 전환, 현금 투입 방식으로 펼쳐 월 부담을 계산하는 순수 함수."""

from datetime import date
from dataclasses import dataclass

from jarvis.core.tools.housing.rules import NO, Area, Limit, Product, Rules, Verdict, eligibility, loan_limit
from jarvis.core.tools.housing.rules import product_years, rate_range
from jarvis.core.tools.housing.profile import HousingProfile
from jarvis.core.tools.housing.loan import annuity_payment

CASH_ALL = "현금 최대 투입"
LOAN_MAX = "대출 최대"
NO_LOAN = "대출 없이"
BASE = "기본"
# 원 단위 반올림 차이로 같은 경우가 둘로 보이지 않게
SAME_WON = 10_000


@dataclass(frozen=True)
class Deposit:
    """임대 주택형의 보증금, 월임대료 한 조합. 기본과 공고문의 최대 전환 조건."""

    label: str
    deposit: int
    rent: int


@dataclass(frozen=True)
class Case:
    price: int  # 분양가나 보증금
    rent: int
    variant: str  # 기본, 보증금 증액 전환, 보증금 감액 전환
    area: Area
    product: Product | None  # None 이면 대출이 필요 없는 경우
    verdict: Verdict
    cash_case: str
    loan: float = 0.0
    cash_used: float = 0.0
    shortfall: float = 0.0  # 현금과 대출로 못 채우는 돈
    rate: tuple[float, float] = (0.0, 0.0)
    years: int | None = None  # None 이면 만기일시(이자만)
    years_note: str | None = None
    limit: Limit | None = None
    pay: tuple[float, float] = (0.0, 0.0)  # 금리 하단, 상단의 월 대출 상환(분양) 또는 월 이자(보증금)
    first_interest: float = 0.0  # 금리 상단 첫 달 이자

    @property
    def monthly(self) -> float:
        """금리 상단 기준 월 부담. 고르고 거를 때는 비싼 쪽으로 본다."""
        return self.pay[1] + self.rent

    @property
    def monthly_low(self) -> float:
        return self.pay[0] + self.rent


def fits(case: Case, monthly_limit: float | None) -> bool:
    if case.verdict.status == NO or case.shortfall > 0:
        return False
    return monthly_limit is None or case.monthly <= monthly_limit


def areas_of(area: Area) -> list[Area]:
    """규제지역인지 모르면 두 경우로 펼친다."""
    if area.regulated is None:
        return [Area(area.capital, True), Area(area.capital, False)]
    return [area]


def purchase_cases(price: int, area: Area, products: list[Product], rules: Rules, profile: HousingProfile,
                   today: date, cash: float, years: int | None, rate: float | None) -> list[Case]:
    cases: list[Case] = []
    need = max(0.0, price - cash)
    for one_area in areas_of(area):
        for product in products:
            verdict = eligibility(product, profile, today, price, one_area)
            if verdict.status == NO:
                cases.append(Case(price, 0, BASE, one_area, product, verdict, CASH_ALL))
                continue
            term, note = product_years(product, rules, one_area, profile, today, years)
            low, high = (rate, rate) if rate is not None else rate_range(product, term, one_area)
            limit = loan_limit(product, rules, profile, today, price, one_area, term, high)
            loans = [(CASH_ALL, min(need, limit.amount))]
            if limit.amount - loans[0][1] >= SAME_WON:
                loans.append((LOAN_MAX, min(limit.amount, float(price))))
            for cash_case, loan in loans:
                used = price - loan
                months = term * 12
                pays = (annuity_payment(loan, low / 100 / 12, months), annuity_payment(loan, high / 100 / 12, months))
                cases.append(Case(
                    price, 0, BASE, one_area, product, verdict, cash_case, loan, min(used, cash),
                    max(0.0, used - cash), (low, high), term, note, limit, pays, loan * high / 100 / 12,
                ))
    return cases


def deposit_cases(deposits: list[Deposit], area: Area, products: list[Product], rules: Rules,
                  profile: HousingProfile, today: date, cash: float, rate: float | None) -> list[Case]:
    """보증금 대출은 만기일시라 매달 이자만 낸다. 현금으로 채워지면 상품과 무관하게 한 경우다."""
    cases: list[Case] = []
    for item in deposits:
        need = max(0.0, item.deposit - cash)
        if need == 0:
            cases.append(Case(item.deposit, item.rent, item.label, area, None, Verdict("가능"), NO_LOAN,
                              cash_used=item.deposit))
            continue
        for product in products:
            verdict = eligibility(product, profile, today, item.deposit, area)
            if verdict.status == NO:
                cases.append(Case(item.deposit, item.rent, item.label, area, product, verdict, CASH_ALL))
                continue
            low, high = (rate, rate) if rate is not None else rate_range(product, 2, area)
            limit = loan_limit(product, rules, profile, today, item.deposit, area, 2, high)
            loan = min(need, limit.amount)
            pays = (loan * low / 100 / 12, loan * high / 100 / 12)
            cases.append(Case(
                item.deposit, item.rent, item.label, area, product, verdict, CASH_ALL, loan,
                min(item.deposit - loan, cash), max(0.0, need - loan), (low, high), None, None, limit, pays, pays[1],
            ))
    return cases
