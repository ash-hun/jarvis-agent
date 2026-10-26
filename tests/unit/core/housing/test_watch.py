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


def test_first_run_reports_what_is_open_then_only_new_notices_come_once(tmp_path):
    board = Board([RENTAL])
    single = HousingProfile(married=False, income=36_000_000)
    tool = HousingWatchTool(board, SeenStore(str(tmp_path)), lambda: TODAY, Profiles(single))

    # 처음에는 지금 공고중인 것 중 가능성이 있는 것을 전부 알린다
    first = _run(tool, {"regions": "강원", "quiet": True})
    assert "지금 공고중인 공고 중 신청 가능성이 있는 것 1건" in first and "태백철암1" in first
    assert _run(tool, {"regions": "강원", "quiet": True}) == ""

    # 새 공고 둘. 미혼에게 신혼희망은 가능성이 낮아 알리지 않는다
    board.notices = [RENTAL, LATER, NEWLYWED]
    text = _run(tool, {"regions": "강원", "quiet": True})
    assert "새 공고 1건" in text and "창원시 행복주택" in text and "광주선운2" not in text
    # 링크는 앞 글과 구분자로 떨어져 있다(디스코드가 목록 안 줄바꿈을 지운다)
    assert " | https://apply.lh.or.kr/" in text
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


class ShBoard:
    """housing_watch 가 쓰는 latest 만 흉내 낸다. 종류마다 최신 글을 준다."""

    def __init__(self, posts: dict, fail: bool = False) -> None:
        self.posts = posts
        self.fail = fail
        self.asked: list[str] = []

    async def latest(self, category):
        from jarvis.core.tools.housing.fetch import FetchError

        self.asked.append(category)
        if self.fail:
            raise FetchError("SH 점검")
        return self.posts.get(category, [])


def _post(seq: str, title: str, status: str = "모집/접수"):
    from jarvis.core.tools.housing.sh_notice import Post

    return Post(seq, title, "주거복지처", "2026-10-20", "120", status)


def test_seoul_watch_also_reads_sh_rental_and_sale_boards(tmp_path):
    sh = ShBoard({
        "임대": [
            _post("301", "2026년 2차 청년매입임대주택 입주자 모집공고"),
            _post("300", "1차 결과 발표", "당첨/발표"),
        ],
        "분양": [_post("401", "고덕강일 신혼희망타운 입주자 모집공고")],
    })
    single = HousingProfile(married=False, income=36_000_000)
    tool = HousingWatchTool(Board([]), SeenStore(str(tmp_path)), lambda: TODAY, Profiles(single), sh=sh)

    first = _run(tool, {"regions": "서울"})
    # 발표 글은 모집이 아니라 빼고, 미혼에게 신혼희망은 가능성이 낮아 뺀다
    assert "[SH] 2026년 2차 청년매입임대주택" in first and "결과 발표" not in first and "고덕강일" not in first
    assert "i-sh.co.kr" in first and "seq=301" in first
    assert _run(tool, {"regions": "서울", "quiet": True}) == ""

    sh.posts["임대"].insert(0, _post("302", "행복주택 예비입주자 모집공고"))
    assert "새 공고 1건" in _run(tool, {"regions": "서울", "quiet": True})


def test_sh_is_only_for_seoul_and_its_failure_keeps_the_lh_report(tmp_path):
    sh = ShBoard({}, fail=True)
    tool = HousingWatchTool(Board([RENTAL]), SeenStore(str(tmp_path)), lambda: TODAY, sh=sh)
    _run(tool, {"regions": "강원"})
    assert sh.asked == []
    text = _run(tool, {"regions": "전국"})
    assert "태백철암1" in text and "SH 조회 실패: SH 점검" in text


def test_watch_without_regions_uses_the_home_regions(tmp_path):
    asked: list[str] = []

    class Recording(Board):
        async def search(self, queries, today):
            asked.extend(q.region for q in queries)
            return await super().search(queries, today)

    home = HousingProfile(married=False, income=36_000_000, regions=("강원",))
    tool = HousingWatchTool(Recording([RENTAL]), SeenStore(str(tmp_path)), lambda: TODAY, Profiles(home))
    assert "(강원)" in _run(tool, {"quiet": True})
    assert set(asked) == {"51"}  # 강원 코드만, 전국("")은 묻지 않았다
