"""housing: rental_complex 가 LH 임대주택 단지 금액을 읽고 공고 제목을 같은 단지에만 보수적으로 맞추는지 검증."""

import pytest

from jarvis.core.tools.housing.rental_complex import complex_query, match_complex, parse_complexes, place_and_block
from jarvis.core.tools.housing.fetch import FetchError
from tests.fixtures.housing_board import page

UNITS = parse_complexes(page("complex_gyeonggi.json"))


def test_complex_query_has_every_field_and_region():
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
def test_place_and_block_reads_title(title, expected):
    assert place_and_block(title) == expected


def test_match_complex_finds_same_complex_and_type():
    rows = match_complex("양주회천 A25BL 국민임대 예비입주자 모집", "국민임대", UNITS)

    assert rows and {r.name for r in rows} == {"양주회천 A25BL 국민·영구임대주택"}
    assert all(r.kind == "국민임대" and r.deposit > 0 for r in rows)


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        # 국민·영구 혼합 단지라도 영구임대 행이 없으면 국민임대 금액을 쓰지 않는다
        ("양주회천 A25BL 영구임대주택 추가입주자 모집", "영구임대"),
        ("의왕청계2 A1블록 신혼희망타운 행복주택", "행복주택(신혼희망)"),
        ("하남시 신혼희망타운 행복주택 예비입주자 모집공고", "행복주택(신혼희망)"),
    ],
    ids=["other_supply_type", "new_complex_without_amounts", "title_without_block"],
)
def test_match_complex_does_not_guess(title, kind):
    assert match_complex(title, kind, UNITS) == []


def test_parse_complexes_raises_fetch_error_on_non_json():
    with pytest.raises(FetchError):
        parse_complexes("<html>점검 중</html>")
