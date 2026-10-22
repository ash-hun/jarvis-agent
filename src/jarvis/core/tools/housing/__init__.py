"""[core] LH, SH 청약 공고를 조회하고 대출 원리금을 계산하는, 정의에 이름을 적은 에이전트만 쓰는 도구 묶음."""

from datetime import date
from collections.abc import Callable

from jarvis.core.tools.housing.fetch import Fetch, FetchBytes, kst_today
from jarvis.core.tools.housing.profile_tool import HousingProfileTool
from jarvis.core.tools.housing.budget import HousingBudgetTool
from jarvis.core.tools.housing.lh_notice import LhNoticeTool
from jarvis.core.tools.housing.sh_notice import ShNoticeTool
from jarvis.core.tools.housing.loan import HousingLoanTool
from jarvis.core.tools.housing.profile import ProfileStore
from jarvis.core.tools.housing.notice_pdf import pdf_text
from jarvis.core.tools.registry import JarvisTool


def housing_tools(
    fetch: Fetch | None = None,
    today: Callable[[], date] = kst_today,
    fetch_file: FetchBytes | None = None,
    read_pdf: Callable[[bytes], str] = pdf_text,
    profiles: ProfileStore | None = None,
) -> list[JarvisTool]:
    """청약 도구를 만든다. 테스트는 가짜 게시판(fetch), 가짜 첨부(fetch_file, read_pdf), 오늘을 넣는다.

    profiles(사용자 기억)가 있어야 주거 프로필 도구가 생기고 housing_budget 이 프로필로 자격을 가린다.
    """
    lh = LhNoticeTool(fetch, today)
    budget = HousingBudgetTool(lh, fetch, today, fetch_file, read_pdf, profiles)
    tools: list[JarvisTool] = [lh, ShNoticeTool(fetch), HousingLoanTool(lh.price_of), budget]
    if profiles is not None:
        tools.append(HousingProfileTool(profiles, today))
    return tools


__all__ = [
    "HousingBudgetTool", "HousingLoanTool", "HousingProfileTool", "LhNoticeTool", "ProfileStore", "ShNoticeTool",
    "housing_tools",
]
