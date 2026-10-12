"""공고문 PDF 의 임대조건 표 읽기. 실제 공고문 세 개에서 꺼낸 텍스트로 본다."""

from jarvis.core.tools.housing.notice_pdf import pick_notice_pdf, rent_terms
from tests.unit.core.housing.conftest import page


def test_thousand_won_table_is_scaled():
    terms = rent_terms(page("rent_terms_uiwang.txt"))
    first_two = [(t.unit, t.deposit, t.rent) for t in terms[:2]]
    assert first_two == [("55A1", 174_800_000, 684_630), ("55A2", 175_200_000, 686_200)]
    assert terms[-1].unit == "55C (주거약자)"


def test_supply_groups_keep_their_label():
    terms = {t.unit: (t.deposit, t.rent) for t in rent_terms(page("rent_terms_seoknam.txt"))}
    assert terms["21A 청년(소득無)"] == (32_708_000, 166_260)
    assert terms["44A 신혼부부·한부모가족"][0] == 81_560_000


def test_area_columns_on_the_same_line_are_ignored():
    terms = rent_terms(page("rent_terms_hanam.txt"))
    assert (terms[0].unit, terms[0].deposit, terms[0].rent) == ("46A", 116_720_000, 486_330)
    # 전환 행((+), (-))은 기본 임대조건이 아니라 빠진다
    assert all(t.deposit not in (174_720_000, 18_720_000) for t in terms)


def test_text_without_rent_section():
    assert rent_terms("모집 공고문\n신청자격 안내") == []


def test_pick_notice_pdf_skips_leaflets_and_forms():
    files = [("1", "공고문.hwpx"), ("2", "팸플릿.pdf"), ("3", "[양식]신청서.pdf"), ("4", "입주자모집공고문.pdf")]
    assert pick_notice_pdf(files) == "4"
    assert pick_notice_pdf([("1", "공고문.hwpx")]) is None
