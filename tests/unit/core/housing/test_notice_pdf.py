"""공고문 PDF 의 임대조건 표와 분양가 표 읽기. 실제 공고문에서 꺼낸 텍스트로 본다."""

from jarvis.core.tools.housing.notice_pdf import pick_notice_pdf, rent_terms, sale_terms
from tests.fixtures.housing_board import page


def test_thousand_won_table_is_scaled():
    terms = rent_terms(page("rent_terms_uiwang.txt"))
    first_two = [(t.unit, t.deposit, t.rent) for t in terms[:2]]
    assert first_two == [("55A1", 174_800_000, 684_630), ("55A2", 175_200_000, 686_200)]
    assert terms[-1].unit == "55C (주거약자)"


def test_supply_groups_keep_their_label():
    terms = {t.unit: (t.deposit, t.rent) for t in rent_terms(page("rent_terms_seoknam.txt"))}
    # 줄이 갈린 공급대상 이름('대학생·' 다음 줄 '청년(소득無)')도 하나로 잇는다
    assert terms["21A 대학생·청년(소득無)"] == (32_708_000, 166_260)
    assert terms["44A 신혼부부·한부모가족"][0] == 81_560_000


def test_area_columns_on_the_same_line_are_ignored():
    terms = rent_terms(page("rent_terms_hanam.txt"))
    assert terms[0].unit.startswith("46A") and (terms[0].deposit, terms[0].rent) == (116_720_000, 486_330)
    # 전환 행((+), (-))은 기본 임대조건이 아니라 그 주택형의 최대 전환 조건이다
    assert all(t.deposit not in (174_720_000, 18_720_000) for t in terms)
    assert terms[0].more == (174_720_000, 196_330) and terms[0].less == (18_720_000, 772_160)


def test_fixed_deposit_split_rows_and_sign_typos():
    """양산: 계약금 '500 (정액)' 이 따로 찍혀 행이 여러 줄로 갈리고, 앞쪽 안내문에도 '임대조건' 이 나온다."""
    terms = rent_terms(page("rent_terms_yangsan.txt"))
    first = terms[0]
    assert (first.unit, first.deposit, first.rent) == ("26 대학생", 17_680_000, 89_280)
    assert first.more == (22_680_000, 64_280) and first.less == (3_680_000, 130_110)
    by_unit = {t.unit: t for t in terms}
    assert by_unit["21 주거급여수급자"].deposit == 13_200_000
    # 공고문이 (+) 로 잘못 찍은 감액 행은 보증금이 줄었으니 감액으로 본다
    assert by_unit["16 소득 有"].less == (2_800_000, 77_870) and by_unit["16 소득 有"].more is None
    assert len(terms) == 16 and all(t.deposit >= 10_000_000 for t in terms)


def test_sale_prices_in_thousand_won_with_merged_deposit():
    """청주: 천원 단위, 계약금 1,000만원이 첫 층에만 찍히고(병합 칸) 다음 층은 칸이 비어 있다."""
    terms = {t.unit: t for t in sale_terms(page("sale_terms_cheongju.txt"))}
    assert list(terms) == ["55A", "55A-1", "55B", "59A", "59A-1", "59B", "59C"]
    assert (terms["55A"].low, terms["55A"].high, terms["55A"].loan) == (288_580_000, 307_000_000, 66_000_000)


def test_sale_prices_in_won_skip_option_tables():
    """대전: 원 단위, 칸이 붙어 뽑힌 행('55,000,000마이너스옵션'), 뒤쪽 옵션 표도 합이 맞지만 가격이 아니다."""
    terms = {t.unit: t for t in sale_terms(page("sale_terms_daejeon.txt"))}
    assert list(terms) == ["59A", "59B", "59C", "59D", "84A", "84B", "84C", "84D"]
    assert (terms["59A"].low, terms["59A"].high) == (313_650_000, 375_500_000)
    assert all(100_000_000 <= t.low <= t.high < 600_000_000 for t in terms.values())


def test_text_without_tables():
    assert rent_terms("모집 공고문\n신청자격 안내") == []
    assert sale_terms("모집 공고문\n신청자격 안내") == []


def test_pick_notice_pdf_skips_leaflets_and_forms():
    files = [("1", "공고문.hwpx"), ("2", "팸플릿.pdf"), ("3", "[양식]신청서.pdf"), ("4", "입주자모집공고문.pdf")]
    assert pick_notice_pdf(files) == "4"
    assert pick_notice_pdf([("1", "공고문.hwpx")]) is None
