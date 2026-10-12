"""[core] LH, SH 청약 공고를 조회하고 대출 원리금을 계산하는, 정의에 이름을 적은 에이전트만 쓰는 도구 묶음."""

from collections.abc import Callable
from datetime import date

from jarvis.core.tools.housing.fetch import Fetch, kst_today
from jarvis.core.tools.housing.lh_notice import LhNoticeTool
from jarvis.core.tools.housing.loan import HousingLoanTool
from jarvis.core.tools.housing.sh_notice import ShNoticeTool
from jarvis.core.tools.registry import JarvisTool


def housing_tools(fetch: Fetch | None = None, today: Callable[[], date] = kst_today) -> list[JarvisTool]:
    """세 도구를 만든다. 테스트는 fetch(가짜 게시판)와 today 를 넣는다."""
    lh = LhNoticeTool(fetch, today)
    return [lh, ShNoticeTool(fetch), HousingLoanTool(lh.price_of)]


__all__ = ["HousingLoanTool", "LhNoticeTool", "ShNoticeTool", "housing_tools"]
