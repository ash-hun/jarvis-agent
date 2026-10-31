"""housing: scenario 가 현금 전부와 대출 최대 경우, 규제 미상이면 두 지역, 보증금 대출은 이자만으로 펼치는지 검증."""

from datetime import date

from jarvis.core.tools.housing.scenario import CASH_ALL, LOAN_MAX, NO_LOAN, Deposit, deposit_cases, fits
from jarvis.core.tools.housing.scenario import purchase_cases
from jarvis.core.tools.housing.profile import HousingProfile
from jarvis.core.tools.housing.rules import Area, load_rules

TODAY = date(2026, 10, 22)
RULES = load_rules()
DEV = HousingProfile(homeless=True, first_home=True, married=False, income=60_000_000, age=28, age_as_of=TODAY)


def products(*ids: str):
    return [p for p in RULES.products if p.id in ids]


def test_purchase_cases_show_cash_all_and_loan_max():
    cases = purchase_cases(300_000_000, Area(False, False), products("bogeumjari"), RULES, DEV, TODAY,
                           150_000_000, None, None)
    assert [c.cash_case for c in cases] == [CASH_ALL, LOAN_MAX]
    cash_all, loan_max = cases
    assert cash_all.loan == 150_000_000 and cash_all.cash_used == 150_000_000
    assert loan_max.loan == 210_000_000 and loan_max.cash_used == 90_000_000  # LTV 70%
    assert round(cash_all.pay[1]) == 814_425  # 1.5억, 연 5.1%, 30년 원리금균등
    assert all(fits(c, 2_000_000) for c in cases)


def test_purchase_cases_report_shortfall_when_limit_is_below_need():
    cases = purchase_cases(500_000_000, Area(False, False), products("bogeumjari"), RULES, DEV, TODAY,
                           100_000_000, None, None)
    assert len(cases) == 1 and cases[0].shortfall == 50_000_000 and not fits(cases[0], None)


def test_purchase_cases_expand_unknown_regulation_into_two_areas():
    cases = purchase_cases(400_000_000, Area(True, None), products("bank_mortgage"), RULES, DEV, TODAY,
                           150_000_000, None, None)
    assert {c.area.regulated for c in cases} == {True, False}


def test_purchase_cases_use_user_rate_over_ranges():
    cases = purchase_cases(300_000_000, Area(False, False), products("bank_mortgage"), RULES, DEV, TODAY,
                           150_000_000, 20, 4.0)
    assert cases[0].rate == (4.0, 4.0) and cases[0].years == 20


def test_deposit_cases_without_loan_is_one_case_and_loan_pays_interest_only():
    deposits = [Deposit("기본", 20_000_000, 90_000), Deposit("보증금 증액 전환", 200_000_000, 50_000)]
    cases = deposit_cases(deposits, Area(False, False), products("bank_jeonse"), RULES, DEV, TODAY,
                          150_000_000, None)
    assert cases[0].cash_case == NO_LOAN and cases[0].monthly == 90_000
    loan = cases[1]
    assert loan.loan == 50_000_000 and loan.years is None
    assert round(loan.pay[0]) == round(50_000_000 * 0.0428 / 12)
    assert loan.monthly == loan.pay[1] + 50_000
