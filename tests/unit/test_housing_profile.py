"""housing: profile 이 사용자가 말한 항목만 바꾸고 같은 값을 다시 넣어도 같으며 저장 형태로 왕복하는지 검증."""

import pytest
from datetime import date

from jarvis.core.tools.housing.profile import HousingProfile, apply_updates, from_metadata, parse_pairs, regions_or_home

TODAY = date(2026, 10, 22)


def test_apply_updates_changes_only_given_fields_and_repeat_is_same():
    base = HousingProfile(homeless=True, income=60_000_000)

    once = apply_updates(base, {"연소득": "7000만", "혼인": "미혼"}, TODAY)

    assert once == HousingProfile(homeless=True, married=False, income=70_000_000)
    assert apply_updates(once, {"연소득": "7000만", "혼인": "미혼"}, TODAY) == once
    assert apply_updates(once, {"연소득": "모름"}, TODAY).income is None


def test_age_on_reads_birth_date_or_age_as_of():
    born = HousingProfile(birth_date=date(1998, 3, 1))
    assert born.age_on(date(2026, 2, 28)) == 27 and born.age_on(date(2026, 3, 1)) == 28
    told = apply_updates(HousingProfile(), {"나이": "만 28세"}, TODAY)
    assert told.age_on(TODAY) == 28 and told.age_on(date(2028, 10, 22)) == 30


@pytest.mark.parametrize(
    ("key", "value"),
    [("키", "180"), ("무주택", "글쎄"), ("생년월일", "1998"), ("관심지역", "화성시청"), ("관심지역", "전국")],
)
def test_apply_updates_rejects_bad_values(key, value):
    with pytest.raises(ValueError):
        apply_updates(HousingProfile(), {key: value}, TODAY)


def test_parse_pairs_and_metadata_round_trip():
    pairs = parse_pairs("연소득=6000만 혼인=미혼, 생애최초 미사용")
    assert pairs == {"연소득": "6000만", "혼인": "미혼", "생애최초": "미사용"}

    profile = apply_updates(HousingProfile(), {**pairs, "생년월일": "2000-01-01"}, TODAY)

    assert from_metadata(profile.metadata()) == profile


def test_apply_updates_reads_household_welfare_and_student_from_spoken_words():
    today = date(2026, 10, 24)

    profile = apply_updates(HousingProfile(), parse_pairs("가구원수=3명, 수급자=아니오, 대학생=재학"), today)

    assert (profile.household, profile.welfare, profile.student) == (3, False, True)
    assert "가구원수: 3명" in profile.lines(today) and "대학생: 예" in profile.lines(today)
    assert apply_updates(profile, {"가구원수": "3인"}, today) == profile
    assert apply_updates(profile, {"가구원수": "모름"}, today).household is None


def test_home_regions_are_saved_once_and_used_when_no_region_is_given():
    saved = apply_updates(HousingProfile(), {"관심지역": "서울, 경기, 서울"}, TODAY)

    assert saved.regions == ("서울", "경기")
    assert apply_updates(saved, {"regions": ["서울", "경기"]}, TODAY) == saved
    assert from_metadata(saved.metadata()) == saved
    assert "관심 지역: 서울, 경기" in saved.lines(TODAY)
    # 도구가 지역을 받았으면 그것, 아니면 관심 지역, 그것도 없으면 전국
    assert regions_or_home("부산", saved) == ["부산"]
    assert regions_or_home("", saved) == ["서울", "경기"]
    assert regions_or_home(None, HousingProfile()) == ["전국"]
    assert apply_updates(saved, {"지역": "모름"}, TODAY).regions is None
