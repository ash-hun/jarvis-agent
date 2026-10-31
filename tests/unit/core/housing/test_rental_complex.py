"""임대주택검색 단지 금액: 응답 읽기와, 공고 제목을 같은 단지에 보수적으로 맞추기."""

import pytest

from jarvis.core.tools.housing.rental_complex import complex_query, match_complex, parse_complexes, place_and_block
from jarvis.core.tools.housing.fetch import FetchError
from tests.fixtures.housing_board import page

UNITS = parse_complexes(page("complex_gyeonggi.json"))


def test_query_has_every_field_and_region():
    query = complex_query("41")
    assert (query["cbo_SearchSiDo"], query["CNP_CD"]) == ("41", "41")
    assert {"cbo_SearchSplTp", "cbo_SearchLsGmy", "cbo_SearchRfe", "listCo", "currPage", "SGG_CD"} <= set(query)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("의왕청계2 A1블록 신혼희망타운 행복주택 입주자 모집공고", ("의왕청계2", "A1")),
        ("양주회천 A25BL 영구임대주택 추가입주자 모집 공고", ("양주회천", "A25")),
        ("의왕고천 A-2블록 신혼희망타운", ("의왕고천", "A2")),
        ("하남시 신혼희망타운 행복주택 예비입주자 모집공고", ("하남시", "")),
        ("[경기북부] 2026년 4차 든든전세주택", ("", "")),
    ],
)
def test_place_and_block(title, expected):
    assert place_and_block(title) == expected


def test_matches_same_complex_and_type():
    rows = match_complex("양주회천 A25BL 국민임대 예비입주자 모집", "국민임대", UNITS)
    assert rows and {r.name for r in rows} == {"양주회천 A25BL 국민·영구임대주택"}
    assert all(r.kind == "국민임대" and r.deposit > 0 for r in rows)


def test_other_supply_type_amounts_are_not_borrowed():
    # 국민·영구 혼합 단지라도 영구임대 행이 없으면 국민임대 금액을 쓰지 않는다
    assert match_complex("양주회천 A25BL 영구임대주택 추가입주자 모집", "영구임대", UNITS) == []


def test_new_complex_without_amounts_is_unknown():
    assert match_complex("의왕청계2 A1블록 신혼희망타운 행복주택", "행복주택(신혼희망)", UNITS) == []


def test_title_without_block_is_not_guessed():
    assert match_complex("하남시 신혼희망타운 행복주택 예비입주자 모집공고", "행복주택(신혼희망)", UNITS) == []


def test_non_json_answer_is_a_fetch_error():
    with pytest.raises(FetchError):
        parse_complexes("<html>점검 중</html>")
