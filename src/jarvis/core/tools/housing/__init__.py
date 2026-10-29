"""[core] LH, SH 청약 공고를 조회, 감시하고 대출 원리금을 계산하는, 정의에 이름을 적은 에이전트만 쓰는 도구 묶음."""

from datetime import date
from typing import TYPE_CHECKING
from collections.abc import Callable

from jarvis.core.tools.housing.fetch import Fetch, FetchBytes, fetch_html, kst_today
from jarvis.core.tools.housing.watch import SEEN_DIR, HousingWatchTool, SeenStore
from jarvis.core.tools.housing.profile_tool import HousingProfileTool
from jarvis.core.tools.housing.budget import HousingBudgetTool
from jarvis.core.tools.housing.lh_notice import LhNoticeTool
from jarvis.core.tools.housing.sh_notice import ShNoticeTool
from jarvis.core.tools.housing.loan import HousingLoanTool
from jarvis.core.tools.housing.profile import ProfileStore
from jarvis.core.tools.housing.sh_terms import sh_pdf_text
from jarvis.core.tools.housing.notice_pdf import pdf_text
from jarvis.core.tools.registry import JarvisTool

if TYPE_CHECKING:
    from jarvis.agent_layer.openloop.store import OpenLoopStore


def housing_tools(
    fetch: Fetch | None = None,
    today: Callable[[], date] = kst_today,
    fetch_file: FetchBytes | None = None,
    read_pdf: Callable[[bytes], str] = pdf_text,
    profiles: ProfileStore | None = None,
    seen_dir: str = SEEN_DIR,
    loops: "OpenLoopStore | None" = None,
) -> list[JarvisTool]:
    """청약 도구를 만든다. 테스트는 가짜 게시판(fetch), 가짜 첨부(fetch_file, read_pdf), 오늘을 넣는다.

    profiles(사용자 기억)가 있어야 주거 프로필 도구가 생기고 housing_budget 이 프로필로 자격을 가린다.
    loops(열린 약속)가 있으면 housing_budget 이 추천 1순위의 마감 전 약속을 남긴다.
    """
    lh = LhNoticeTool(fetch, today, profiles)
    # 가짜 공고문(read_pdf)을 넣은 테스트는 SH 공고문도 그것으로 읽는다. 실제는 분양 가격표까지 쪽 수를 늘려 읽는다
    read_sh = sh_pdf_text if read_pdf is pdf_text else read_pdf
    budget = HousingBudgetTool(
        lh, fetch, today, fetch_file, read_pdf, profiles, loops=loops, sh_fetch=fetch or fetch_html, read_sh_pdf=read_sh
    )
    sh = ShNoticeTool(fetch)
    watch = HousingWatchTool(lh, SeenStore(seen_dir), today, profiles, sh=sh)
    tools: list[JarvisTool] = [lh, sh, HousingLoanTool(lh.price_of), budget, watch]
    if profiles is not None:
        tools.append(HousingProfileTool(profiles, today))
    return tools


__all__ = [
    "HousingBudgetTool", "HousingLoanTool", "HousingProfileTool", "HousingWatchTool", "LhNoticeTool", "ProfileStore",
    "ShNoticeTool", "housing_tools",
]
