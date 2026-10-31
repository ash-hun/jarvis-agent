"""[core] 추천한 공고의 마감 며칠 전을 열린 약속으로 남겨 에이전트가 먼저 말할 근거로 삼는다."""

from typing import TYPE_CHECKING
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta

from jarvis.agent_layer.openloop.openloop_types import OpenLoop
from jarvis.core.tools.housing.markup import parse_date
from jarvis.core.tools.housing.fetch import KST_OFFSET
from jarvis.core.tools.housing.lh_notice import Notice
from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.agent_layer.openloop.openloop_store import OpenLoopStore

# 마감 사흘 전 아침. 공고문을 다시 보고 서류를 챙길 시간이다
LEAD_DAYS = 3
REMIND_AT = time(9, 0)
# 사흘이 안 남았으면 전날 아침. 그것도 지났으면 방금 한 답으로 충분하다
LAST_LEAD_DAYS = 1

logger = get_logger(__name__)


def remind_date(closes: date, today: date) -> date | None:
    """알릴 날. 오늘보다 뒤여야 한다(오늘 알릴 것은 방금 한 답이 이미 말했다). 순수 함수."""
    for lead in (LEAD_DAYS, LAST_LEAD_DAYS):
        day = closes - timedelta(days=lead)
        if day > today:
            return day
    return None


def loop_id(session_id: str, notice_id: str) -> str:
    """같은 세션에서 같은 공고는 약속 하나다. 다시 추천해도, 사용자가 이미 닫았어도 새로 만들지 않는다."""
    return f"housing-deadline:{session_id}:{notice_id}"


def deadline_loop(notice: Notice, session_id: str, agent_id: str, today: date) -> OpenLoop | None:
    """공고 하나의 마감 전 약속. 마감을 모르거나 알릴 날이 없으면 None. 순수 함수."""
    closes = parse_date(notice.closes)
    day = remind_date(closes, today) if closes is not None else None
    if closes is None or day is None:
        return None
    due = datetime.combine(day, REMIND_AT, tzinfo=UTC) - KST_OFFSET
    return OpenLoop(
        id=loop_id(session_id, notice.id),
        description=f"추천한 공고 '{notice.title}' 마감 {closes.isoformat()}. 신청할지 다시 확인하도록 알리기",
        origin_session=session_id,
        agent_id=agent_id,
        due_ms=int(due.timestamp() * 1000),
    )


async def track_deadlines(
    store: "OpenLoopStore", notices: Iterable[Notice], session_id: str, agent_id: str, today: date
) -> list[Notice]:
    """마감 전 약속을 맞춘다. 이미 있는 약속(닫힌 것 포함)은 건드리지 않는다. 새로 남긴 공고를 돌려준다.

    두 번 불러도 약속은 공고마다 하나다. 실패는 추천 답을 막지 않게 로그만 남긴다.
    """
    added = []
    for notice in notices:
        loop = deadline_loop(notice, session_id, agent_id, today)
        if loop is None:
            continue
        try:
            if await store.get(loop.id) is None:
                await store.add(loop)
                added.append(notice)
        except Exception as exc:
            logger.warning(f"[Housing] 마감 약속을 남기지 못했다 {notice.id}: {exc!r}")
    return added
