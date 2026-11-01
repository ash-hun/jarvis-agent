"""[core] 성찰 항목(약속, 외부 이벤트)에서 남은 시간과 처리 신호를 정규식과 순수 함수로 계산한다."""

# 외부 이벤트 글은 신뢰하지 않는 입력이다. 모델에 해석을 맡기지 않고 정규식으로 읽으며, 못 읽으면 "모름"(None)으로 둔다.
# "모름" 은 판단 재료일 뿐 침묵의 근거로 쓰지 않는다.

import re
from datetime import date, datetime, timedelta

from jarvis.agent_layer.thought.thought_types import SituationFact

# 이벤트 앞의 출처 꼬리표("[ci]", "[1]")는 시각이나 신호가 아니다
TAG = re.compile(r"^\s*(\[[^\]]{1,24}\]\s*)+")
ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
KO_DATE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
DAY_WORD = re.compile(r"(오늘|내일|모레|어제)")
# 시각은 "10:30", "오후 2시", "9시 40분", "9시 반" 처럼 콜론이나 "시" 가 붙은 것만 읽는다.
# "3 failed", "1,284,300원" 을 시각으로 읽지 않게
CLOCK = re.compile(r"(오전|오후)?\s*(\d{1,2})(?::(\d{2})|시(?:\s*(\d{1,2})분|\s*(반))?)")
DAY_OFFSET = {"어제": -1, "오늘": 0, "내일": 1, "모레": 2}
# 날짜 표기가 시각보다 이만큼 앞에 있으면 그 날짜의 시각으로 본다
DATE_REACH = 14
# 먼저 걸리는 신호를 쓴다. 취소는 처리가 아니라 새 소식일 수 있어 따로 둔다
SIGNALS = (
    ("취소", re.compile(r"취소|cancel+ed|철회", re.IGNORECASE)),
    ("수락", re.compile(r"수락|accepted|승인(?:됨|되었|했)|approved", re.IGNORECASE)),
    ("확인", re.compile(r"확인(?:함|했|되었|됨|완료)|confirmed|acknowledged", re.IGNORECASE)),
    (
        "완료",
        re.compile(
            r"완료|결제되었|출금되었|납부되었|성공|succeeded|passed|completed|delivered|resolved|merged|paid",
            re.IGNORECASE,
        ),
    ),
)
# 실패나 부족이 함께 적혀 있으면 처리된 것이 아니다("결제 실패", "빌드 완료(테스트 3 실패)")
# "제출 완료 여부 미확인" 처럼 아직 모른다는 말이 붙어도 처리된 것이 아니다
FAILURE = re.compile(
    r"실패|failed|failure|error|오류|부족|미납|연체|지연|delayed|거절|declined|rejected|여부|미확인|아직|않았",
    re.IGNORECASE,
)


def situation_facts(
    open_loops: list[tuple[str, datetime | None]], events: list[str], now: datetime
) -> list[SituationFact]:
    """약속(설명, 기한)과 이벤트 줄마다 사실 하나. 약속은 기한을, 이벤트는 글에 적힌 시각을 쓴다. 순수 함수."""
    facts = [loop_fact(text, due, now) for text, due in open_loops]
    return facts + [event_fact(line, now) for line in events]


def loop_fact(text: str, due: datetime | None, now: datetime) -> SituationFact:
    """기한이 있으면 그 기한까지, 없으면 글에 적힌 시각까지. 순수 함수."""
    if due is None:
        days, minutes = mentioned_time(text, now)
    else:
        days, minutes = (due.date() - now.date()).days, _minutes(due, now)
    return SituationFact(text=text, source="loop", days=days, minutes=minutes, signal=handled_signal(text))


def event_fact(line: str, now: datetime) -> SituationFact:
    days, minutes = mentioned_time(line, now)
    return SituationFact(text=line, source="event", days=days, minutes=minutes, signal=handled_signal(line))


def handled_signal(text: str) -> str | None:
    """글에 처리 신호(수락, 완료, 취소, 확인)가 있으면 그 이름. 실패나 부족이 같이 있으면 None. 순수 함수."""
    body = TAG.sub("", text)
    if FAILURE.search(body):
        return None
    return next((name for name, pattern in SIGNALS if pattern.search(body)), None)


def mentioned_time(text: str, now: datetime) -> tuple[int | None, int | None]:
    """글에 적힌 시각 중 대표 하나까지 남은 (날, 분). 앞으로 올 시각 중 가장 가까운 것, 없으면 가장 늦은 지난 시각.

    시각 없이 날짜만 있으면 (날, None), 둘 다 없으면 (None, None). 순수 함수.
    """
    body = TAG.sub("", text)
    dates = _dates(body, now)
    moments: list[datetime] = []
    for match in CLOCK.finditer(body):
        clock = _clock(match)
        if clock is None:
            continue
        day = _date_before(dates, match.start()) or now.date()
        moments.append(datetime.combine(day, datetime.min.time()) + clock)
    if moments:
        future = [m for m in moments if m >= now]
        chosen = min(future) if future else max(moments)
        return (chosen.date() - now.date()).days, _minutes(chosen, now)
    if dates:
        return (min(d for _, d in dates) - now.date()).days, None
    return None, None


def _dates(body: str, now: datetime) -> list[tuple[int, date]]:
    """(끝 위치, 날짜) 목록."""
    found: list[tuple[int, date]] = []
    for m in ISO_DATE.finditer(body):
        parsed = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if parsed is not None:
            found.append((m.end(), parsed))
    for m in KO_DATE.finditer(body):
        # 해가 없으면 지금과 가장 가까운 해로 본다(1월 1일의 "12월 31일" 은 어제다)
        years = (_safe_date(y, int(m.group(1)), int(m.group(2))) for y in (now.year - 1, now.year, now.year + 1))
        candidates = [d for d in years if d is not None]
        if candidates:
            found.append((m.end(), min(candidates, key=lambda d: abs((d - now.date()).days))))
    for m in DAY_WORD.finditer(body):
        found.append((m.end(), now.date() + timedelta(days=DAY_OFFSET[m.group(1)])))
    return sorted(found)


def _date_before(dates: list[tuple[int, date]], position: int) -> date | None:
    near = [d for end, d in dates if 0 <= position - end <= DATE_REACH]
    return near[-1] if near else None


def _clock(match: re.Match[str]) -> timedelta | None:
    meridiem, hour_text, colon_minute, ko_minute, half = match.groups()
    hour, minute = int(hour_text), 30 if half else int(colon_minute or ko_minute or 0)
    if meridiem == "오후" and hour < 12:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return timedelta(hours=hour, minutes=minute)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _minutes(moment: datetime, now: datetime) -> int:
    return int((moment - now).total_seconds() // 60)
