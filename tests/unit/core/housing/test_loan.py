"""housing_loan: 상환 방식별 원리금, 연차 합계, 대출원금 정하기, 금리 역산."""

import asyncio

import pytest

from jarvis.core.tools.housing.loan import (
    HousingLoanTool,
    annuity_payment,
    calculate,
    resolve_principal,
    schedule,
    solve_rate,
    won,
    yearly,
)


def test_annuity_matches_known_value():
    # 1억, 연 3%, 30년 원리금균등의 월 상환액은 421,604원으로 알려져 있다
    assert round(annuity_payment(100_000_000, 0.03 / 12, 360)) == 421_604
    assert annuity_payment(1_200, 0.0, 12) == 100


@pytest.mark.parametrize("method", ["원리금균등", "원금균등", "만기일시"])
def test_schedule_repays_exactly_the_principal(method):
    rows = schedule(300_000_000, 4.0, 240, method, grace_months=12)
    assert len(rows) == 240
    assert sum(m.principal for m in rows) == pytest.approx(300_000_000)
    assert rows[-1].balance == pytest.approx(0, abs=1e-6)
    # 거치 동안은 이자만 낸다
    assert rows[0].principal == 0 and rows[0].interest == pytest.approx(1_000_000)


def test_equal_principal_payment_shrinks():
    rows = schedule(120_000_000, 6.0, 120, "원금균등")
    assert rows[0].principal == pytest.approx(1_000_000)
    assert rows[0].payment > rows[-1].payment


def test_bullet_pays_interest_then_principal():
    rows = schedule(100_000_000, 3.0, 12, "만기일시")
    assert all(m.principal == 0 for m in rows[:-1])
    assert rows[-1].principal == pytest.approx(100_000_000)


def test_yearly_sums_months():
    years = yearly(schedule(100_000_000, 3.0, 36, "원리금균등"))
    assert [y.index for y in years] == [1, 2, 3]
    assert years[0].payment == pytest.approx(12 * annuity_payment(100_000_000, 0.0025, 36))


def test_solve_rate_round_trip():
    payment = annuity_payment(300_000_000, 0.035 / 12, 360)
    assert solve_rate(300_000_000, payment, 360) == pytest.approx(3.5, abs=1e-6)
    assert solve_rate(300_000_000, 100_000, 360) is None


def test_principal_from_price():
    assert resolve_principal({"price": 500_000_000, "ltv_percent": 70})[0] == pytest.approx(350_000_000)
    assert resolve_principal({"price": 500_000_000, "down_payment": 200_000_000})[0] == 300_000_000
    assert resolve_principal({"principal": 1, "price": 9})[0] == 1
    assert resolve_principal({"price": 500_000_000})[0] is None


def test_won_reading():
    assert won(353_138_800) == "353,138,800원(약 3억 5,314만원)"
    assert won(300_000_000) == "300,000,000원(약 3억원)"
    assert won(9_999) == "9,999원"


def test_report_for_a_sale_price():
    text = calculate({"price": 504_484_000, "ltv_percent": 70, "annual_rate_percent": 3.5, "years": 30})
    assert "대출원금 353,138,800원" in text
    assert "월 상환액 1,585,751원" in text
    assert "1년차 연간 상환액 19,029,012원" in text
    assert "30년차" in text and "…" in text


def test_report_when_solving_rate():
    text = calculate({"principal": 300_000_000, "monthly_payment": 1_347_000, "years": 30})
    assert "(월 상환액에서 역산)" in text and "연 3.49" in text


@pytest.mark.parametrize(
    "params",
    [
        {"years": 30, "annual_rate_percent": 3},
        {"principal": 1e8, "years": 0, "annual_rate_percent": 3},
        {"principal": 1e8, "years": 10, "grace_years": 10, "annual_rate_percent": 3},
        {"principal": 1e8, "years": 10, "method": "체증식", "annual_rate_percent": 3},
        {"principal": 1e8, "years": 10},
        {"principal": 1e8, "years": 10, "monthly_payment": 1e6, "method": "원금균등"},
    ],
)
def test_bad_input_is_an_error_result(params):
    result = asyncio.run(HousingLoanTool().execute("t1", params))
    assert result.is_error and "계산할 수 없다" in result.content[0].text


def test_same_input_same_answer():
    params = {"principal": 2e8, "annual_rate_percent": 4.2, "years": 25, "method": "원금균등"}
    assert calculate(params) == calculate(params)


def test_loan_from_notice_id_and_unit(lh_board):
    from jarvis.core.tools.housing import housing_tools
    from tests.unit.core.housing.conftest import TODAY

    loan = housing_tools(lh_board, lambda: TODAY)[2]
    params = {"notice_id": "0000061179-02-39-39", "unit": "55A", "ltv_percent": 70, "annual_rate_percent": 3.5,
              "years": 30}
    result = asyncio.run(loan.execute("t1", params))
    text = result.content[0].text
    assert not result.is_error
    assert "인천계양 A17블록 신혼희망타운(공공분양) 입주자모집공고 55.9000A 평균분양가격(원) 504,484,000원" in text
    assert "월 상환액 1,585,751원" in text


def test_loan_from_notice_reports_board_failure():
    from jarvis.core.tools.housing import housing_tools
    from tests.unit.core.housing.conftest import TODAY, FakeBoard

    loan = housing_tools(FakeBoard({}), lambda: TODAY)[2]
    result = asyncio.run(loan.execute("t1", {"notice_id": "0000061179-02-39-39", "years": 30, "ltv_percent": 70,
                                             "annual_rate_percent": 3.5}))
    assert result.is_error and "공고 금액을 읽지 못했다" in result.content[0].text


def test_loan_without_notice_reader_asks_for_price():
    result = asyncio.run(HousingLoanTool().execute("t1", {"notice_id": "1", "years": 30, "annual_rate_percent": 3}))
    assert result.is_error and "price 를 직접" in result.content[0].text
