"""대출 규칙: 프로필로 자격을 가르고, 한도는 상품 한도, LTV, 규제 한도, DSR/DTI 중 가장 작은 값이다."""

from datetime import date
from dataclasses import replace

from jarvis.core.tools.housing.rules import NO, OK, UNKNOWN, Area, eligibility, load_rules, loan_limit, notice_access
from jarvis.core.tools.housing.profile import HousingProfile
from jarvis.core.tools.housing.rules import rate_range

TODAY = date(2026, 10, 22)
RULES = load_rules()
# 개발자 사례: 무주택, 생애최초 미사용, 미혼, 연소득 6천, 만 28세
DEV = HousingProfile(homeless=True, first_home=True, married=False, income=60_000_000, age=28, age_as_of=TODAY)
SEOUL, JEONBUK, GYEONGGI = Area(True, True), Area(False, False), Area(True, None)


def product(pid: str):
    return next(p for p in RULES.products if p.id == pid)


def test_rules_file_has_sources_and_date():
    assert RULES.checked == date(2026, 10, 22)
    assert all(p.get("source") for p in RULES.products)
    assert not RULES.stale(TODAY) and RULES.stale(date(2027, 1, 1))


def test_developer_case_eligibility():
    assert eligibility(product("didimdol"), DEV, TODAY).status == NO
    assert eligibility(product("beotimmok"), DEV, TODAY).status == NO
    assert eligibility(product("youth_beotimmok"), DEV, TODAY).status == NO
    assert eligibility(product("bogeumjari"), DEV, TODAY).status == OK
    assert eligibility(product("bank_mortgage"), DEV, TODAY).status == OK
    # 만 30세가 되면 디딤돌 나이 제한이 풀린다(순자산을 몰라 미확인으로 남는다)
    older = eligibility(product("didimdol"), DEV, date(2028, 10, 22))
    assert older.status == UNKNOWN and older.reasons == ("순자산 5.11억원 이하",)


def test_unknown_profile_marks_conditions_instead_of_rejecting():
    verdict = eligibility(product("beotimmok"), HousingProfile(), TODAY)
    assert verdict.status == UNKNOWN and "연소득 5,000만원 이하" in verdict.reasons


def test_price_cap_rejects_with_reason():
    verdict = eligibility(product("bogeumjari"), DEV, TODAY, 700_000_000, JEONBUK)
    assert verdict.status == NO and verdict.reasons == ("집값 6억원 이하",)


def test_area_from_region_and_title():
    assert RULES.area("서울특별시", "아무 공고") == Area(True, True)
    assert RULES.area("경기도", "의왕청계2 A1블록") == Area(True, True)
    assert RULES.area("경기도", "화성동탄2 A1블록") == Area(True, None)
    assert RULES.area("인천광역시", "인천계양") == Area(True, False)
    assert RULES.area("전북특별자치도", "익산평화") == Area(False, False)


def test_market_mortgage_limit_is_the_smallest_of_ltv_cap_and_dsr():
    limit = loan_limit(product("bank_mortgage"), RULES, DEV, TODAY, 300_000_000, JEONBUK, 30, 6.0)
    names = [name for name, _ in limit.parts]
    assert names == ["LTV 80%", "DSR 40%(스트레스 +0.75%p)"]
    assert limit.amount == 240_000_000
    seoul = loan_limit(product("bank_mortgage"), RULES, DEV, TODAY, 1_000_000_000, SEOUL, 30, 6.0)
    # 서울 생애최초 LTV 70% 7억, 주담대 한도 6억, DSR(스트레스 3%p) 이 가장 작다
    assert seoul.amount == min(v for _, v in seoul.parts) and seoul.amount < 300_000_000


def test_policy_limit_uses_first_home_cap_and_dti():
    limit = loan_limit(product("bogeumjari"), RULES, DEV, TODAY, 700_000_000, JEONBUK, 30, 5.1)
    assert dict(limit.parts)["상품 한도"] == 420_000_000
    assert limit.amount == 420_000_000


def test_bogeumjari_rate_adds_regulated_spread():
    assert rate_range(product("bogeumjari"), 30, JEONBUK) == (5.1, 5.1)
    assert rate_range(product("bogeumjari"), 30, SEOUL) == (5.3, 5.3)
    assert rate_range(product("bank_jeonse"), 2, SEOUL) == (4.28, 4.81)


def test_notice_access_by_kind_and_profile():
    """공고 유형의 신청 자격은 판정이 아니라 가능성이다. 소득 기준은 2026년 공고문의 1인 가구 금액이다."""
    married_only = notice_access(RULES, "공공분양(신혼희망)", "광주선운2 선착순계약", DEV)
    assert married_only.status == NO and "예비신혼부부" in married_only.reasons[0]
    assert notice_access(RULES, "공공분양(신혼희망)", "x", HousingProfile()).status == UNKNOWN
    # 월 500만원은 영구임대 일반 1인 기준 2,669,354원을 넘는다
    permanent = notice_access(RULES, "영구임대", "대전광역시 영구임대주택 예비입주자 모집", DEV)
    assert permanent.status == NO and "월 2,669,354원 이하" in permanent.reasons[0]
    assert notice_access(RULES, "영구임대", "남원노암단지 영구임대주택 입주자격완화 예비입주자 모집", DEV).status == OK
    low = HousingProfile(income=36_000_000)
    assert notice_access(RULES, "행복주택", "창원시 행복주택 예비입주자 모집", low).status == OK
    assert notice_access(RULES, "분양주택", "익산평화 공공분양주택", DEV).status == UNKNOWN


def test_notice_access_uses_household_welfare_and_student():
    """1인 기준을 넘어도 가구원이 많으면 단정하지 않고, 수급자와 대학생은 일반 기준을 대지 않는다."""
    title = "대전광역시 영구임대주택 예비입주자 모집"
    alone = replace(DEV, household=1)
    assert notice_access(RULES, "영구임대", title, alone).status == NO
    assert "가구원" not in " ".join(notice_access(RULES, "영구임대", title, alone).reasons)
    family = notice_access(RULES, "영구임대", title, replace(DEV, household=3))
    assert family.status == UNKNOWN and "3인 가구" in family.reasons[1]
    welfare = notice_access(RULES, "영구임대", title, replace(DEV, welfare=True))
    assert welfare.status == OK and "수급자" in welfare.reasons[0]
    # 국민임대에는 수급자 경로를 적지 않았다. 일반 기준으로 댄다
    assert notice_access(RULES, "국민임대", "태백철암1 국민임대", replace(DEV, welfare=True)).status == NO
    student = notice_access(RULES, "행복주택", "창원시 행복주택 예비입주자 모집", replace(DEV, student=True))
    assert student.status == UNKNOWN and "대학생" in student.reasons[0]
