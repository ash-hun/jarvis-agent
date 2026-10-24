"""housing_watch: 지역마다 본 공고를 기억하고, 새 공고 중 프로필로 신청 가능성이 있는 것만 한 번 알린다."""

import asyncio

from jarvis.core.tools.housing.watch import HousingWatchTool, SeenStore, watch_key
from jarvis.core.tools.housing.profile import HousingProfile
from jarvis.core.tools.housing.lh_notice import Notice
from tests.unit.core.housing.conftest import TODAY

RENTAL = Notice(
    "2015122300020803-03-06-10", "국민임대", "태백철암1 국민임대", "강원특별자치도",
    "2026.10.01", "2026.11.20", "공고중",
)
LATER = Notice(
    "2015122300020900-03-06-10", "행복주택", "창원시 행복주택 예비입주자 모집", "경상남도",
    "2026.10.21", "2026.11.30", "공고중",
)
NEWLYWED = Notice(
    "0000061200-03-05-05", "공공분양(신혼희망)", "광주선운2 선착순계약", "광주광역시",
    "2026.10.21", "2026.11.25", "공고중",
)


class Board:
    """housing_watch 가 쓰는 search 만 흉내 낸다. 지역과 상관없이 지금 걸린 공고를 준다."""

    def __init__(self, notices: list[Notice]) -> None:
        self.notices = notices

    async def search(self, queries, today):
        return [("임대", len(self.notices), list(self.notices))]


class Profiles:
    def __init__(self, profile: HousingProfile) -> None:
        self.profile = profile

    async def get(self, user_id: str) -> HousingProfile:
        return self.profile


def _run(tool: HousingWatchTool, params: dict) -> str:
    result = asyncio.run(tool.execute("t", params))
    assert not result.is_error, result.content[0].text
    return result.content[0].text


def test_first_run_sets_a_baseline_then_only_new_notices_come_once(tmp_path):
    board = Board([RENTAL])
    single = HousingProfile(married=False, income=36_000_000)
    tool = HousingWatchTool(board, SeenStore(str(tmp_path)), lambda: TODAY, Profiles(single))

    assert "기준으로 삼았다" in _run(tool, {"regions": "강원", "quiet": True})
    assert _run(tool, {"regions": "강원", "quiet": True}) == ""

    # 새 공고 둘. 미혼에게 신혼희망은 가능성이 낮아 알리지 않는다
    board.notices = [RENTAL, LATER, NEWLYWED]
    text = _run(tool, {"regions": "강원", "quiet": True})
    assert "새 LH 공고 1건" in text and "창원시 행복주택" in text and "광주선운2" not in text
    # 다시 불러도 같은 공고는 오지 않는다
    assert _run(tool, {"regions": "강원", "quiet": True}) == ""
    assert "새로 알릴 공고가 없다" in _run(tool, {"regions": "강원"})


def test_watch_key_is_per_user_and_region_set(tmp_path):
    assert watch_key("local", ["서울", "경기"]) == watch_key("local", ["경기", "서울", "서울"])
    assert watch_key("local", ["서울"]) != watch_key("other", ["서울"])
    store = SeenStore(str(tmp_path / "seen"))
    assert store.load("k") is None
    store.save("k", ["서울"], ["a", "b"])
    store.save("k", ["서울"], ["a", "b"])
    assert store.load("k") == ["a", "b"]


def test_unknown_region_is_an_error(tmp_path):
    tool = HousingWatchTool(Board([]), SeenStore(str(tmp_path)), lambda: TODAY)
    result = asyncio.run(tool.execute("t", {"regions": "아틀란티스"}))
    assert result.is_error and "모르는 지역" in result.content[0].text
