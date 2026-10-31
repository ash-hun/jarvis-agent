"""housing: fetch 의 KST 오늘이 날짜를 돌려주는지 검증."""

from datetime import date

from jarvis.core.tools.housing.fetch import kst_today


def test_kst_today_returns_a_date():
    assert isinstance(kst_today(), date)
