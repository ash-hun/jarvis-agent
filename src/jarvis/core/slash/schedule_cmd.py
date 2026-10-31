"""[core] 한국어 시각 표현을 해석해 한 번 실행 또는 반복 작업으로 스케줄러에 등록하는 /schedule 핸들러 factory."""

import re
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from collections.abc import Awaitable, Callable

from jarvis.core.scheduler.task import ONCE_PREFIX, SLASH_PREFIX

if TYPE_CHECKING:
    from jarvis.core.scheduler.scheduler_service import SchedulerService
    from jarvis.core.slash.dispatcher import ScopedHandler
    from jarvis.core.scheduler.task import ScheduledTask
    from jarvis.memory.scope import MemoryScope

# YYYY.MM.DD 오전/오후 N시까지 <prompt>
_KO_AMPM_RE = re.compile(
    r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(오전|오후)\s*(\d{1,2})시까지\s+(.*)",
    re.DOTALL,
)
# YYYY.MM.DD HH:MM까지 <prompt>
_24H_RE = re.compile(
    r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})까지\s+(.*)",
    re.DOTALL,
)


def parse_deadline(args: str) -> tuple[datetime, str] | None:
    """
    '/schedule' 이후 인자에서 마감 시간과 프롬프트를 파싱한다.
    성공 시 (deadline_datetime, prompt_text) 반환.
    실패 시 None 반환.
    """
    m = _KO_AMPM_RE.match(args.strip())
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ampm, hour = m.group(4), int(m.group(5))
        if ampm == "오후" and hour < 12:
            hour += 12
        elif ampm == "오전" and hour == 12:
            hour = 0
        return datetime(year, month, day, hour, 0), m.group(6).strip()

    m = _24H_RE.match(args.strip())
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
        return datetime(year, month, day, hour, minute), m.group(6).strip()

    return None


# ── "~에": 정한 시각에 한 번 ──────────────────────────────────────────────────
# N분/시간/일 뒤(후)에 <prompt>
_REL_RE = re.compile(r"^(\d+)\s*(분|시간|일)\s*(?:뒤|후)에?\s+(.*)", re.DOTALL)
# YYYY.MM.DD 오전/오후 N시[ M분]에 <prompt>
_DATE_AMPM_AT_RE = re.compile(
    r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(오전|오후)\s*(\d{1,2})시(?:\s*(\d{1,2})분)?에\s+(.*)",
    re.DOTALL,
)
# YYYY.MM.DD HH:MM에 <prompt>
_DATE_24H_AT_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})에\s+(.*)", re.DOTALL)
# [오늘|내일|모레] 오전/오후 N시[ M분]에 <prompt>
_DAY_AMPM_AT_RE = re.compile(
    r"^(?:(오늘|내일|모레)\s*)?(오전|오후)\s*(\d{1,2})시(?:\s*(\d{1,2})분)?에\s+(.*)",
    re.DOTALL,
)
# [오늘|내일|모레] HH:MM에 <prompt>
_DAY_24H_AT_RE = re.compile(r"^(?:(오늘|내일|모레)\s*)?(\d{1,2}):(\d{2})에\s+(.*)", re.DOTALL)

_DAY_OFFSET = {"오늘": 0, "내일": 1, "모레": 2}


def _to_24h(ampm: str, hour: int) -> int:
    if ampm == "오후" and hour < 12:
        return hour + 12
    if ampm == "오전" and hour == 12:
        return 0
    return hour


def _on_day(now: datetime, day: str | None, hour: int, minute: int) -> datetime:
    """오늘/내일/모레의 그 시각. 날짜 말이 없고 시각이 이미 지났으면 내일로 넘긴다."""
    at = (now + timedelta(days=_DAY_OFFSET.get(day or "", 0))).replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )
    if day is None and at <= now:
        at += timedelta(days=1)
    return at


def parse_once(args: str, now: datetime | None = None) -> tuple[datetime, str] | None:
    """
    '/schedule' 인자에서 "~에"(한 번 실행) 시각과 프롬프트를 파싱한다.
    형식: 'N분 뒤에', '오후 7시에', '내일 09:30에', '2026.10.01 오후 7시에'.
    실패 시 None.
    """
    now = now or datetime.now()
    text = args.strip()

    m = _REL_RE.match(text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"분": timedelta(minutes=n), "시간": timedelta(hours=n), "일": timedelta(days=n)}[unit]
        return (now + delta).replace(microsecond=0), m.group(3).strip()

    m = _DATE_AMPM_AT_RE.match(text)
    if m:
        hour = _to_24h(m.group(4), int(m.group(5)))
        minute = int(m.group(6) or 0)
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hour, minute), m.group(7).strip()

    m = _DATE_24H_AT_RE.match(text)
    if m:
        return (
            datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))),
            m.group(6).strip(),
        )

    m = _DAY_AMPM_AT_RE.match(text)
    if m:
        hour = _to_24h(m.group(2), int(m.group(3)))
        return _on_day(now, m.group(1), hour, int(m.group(4) or 0)), m.group(5).strip()

    m = _DAY_24H_AT_RE.match(text)
    if m:
        return _on_day(now, m.group(1), int(m.group(2)), int(m.group(3))), m.group(4).strip()

    return None


def infer_schedule(deadline: datetime) -> str:
    """마감까지 남은 시간에 따라 적합한 cron 표현식을 결정한다."""
    now = datetime.now()
    delta = deadline - now
    total_hours = delta.total_seconds() / 3600

    if total_hours >= 24 * 7:
        return "0 9 * * *"  # 매일 오전 9시
    elif total_hours >= 24:
        return "0 0,6,12,18 * * *"  # 6시간마다
    elif total_hours >= 1:
        return "0 * * * *"  # 매시간
    else:
        return "*/10 * * * *"  # 10분마다 (마감 임박)


_FREQ_LABELS: dict[str, str] = {
    "0 9 * * *": "매일 오전 9시",
    "0 0,6,12,18 * * *": "6시간마다",
    "0 * * * *": "매시간",
    "*/10 * * * *": "10분마다",
}


def build_schedule_task(deadline: datetime, prompt: str) -> "ScheduledTask":
    """파싱된 마감/프롬프트로 ScheduledTask를 생성한다."""
    from jarvis.core.scheduler.task import ScheduledTask

    schedule = infer_schedule(deadline)
    name = f"{SLASH_PREFIX}{uuid.uuid4().hex[:8]}"
    return ScheduledTask(
        name=name,
        schedule=schedule,
        prompt=prompt,
        run_until=deadline,
        enabled=True,
        description=f"슬래시 명령 생성 | 마감: {deadline.strftime('%Y.%m.%d %H:%M')}",
    )


def build_once_task(run_at: datetime, prompt: str, kind: Literal["reminder", "task"]) -> "ScheduledTask":
    """정한 시각에 한 번 실행되는 작업을 만든다."""
    from jarvis.core.scheduler.task import ScheduledTask

    return ScheduledTask(
        name=f"{ONCE_PREFIX}{uuid.uuid4().hex[:8]}",
        prompt=prompt,
        run_at=run_at,
        kind=kind,
        enabled=True,
        description=f"슬래시 명령 생성 | {run_at.strftime('%Y.%m.%d %H:%M')} 한 번",
    )


def _fmt_left(run_at: datetime, now: datetime) -> str:
    mins = max(0, round((run_at - now).total_seconds() / 60))
    if mins < 60:
        return f"{mins}분 뒤"
    if mins < 1440:
        return f"{mins // 60}시간 {mins % 60}분 뒤" if mins % 60 else f"{mins // 60}시간 뒤"
    return f"{mins // 1440}일 뒤"


def format_once_confirmation(task: "ScheduledTask", now: datetime) -> str:
    assert task.run_at is not None
    kind = "알림 — 문구를 그대로 알려드림" if task.kind == "reminder" else "작업 — 실행한 결과를 알려드림"
    prompt_preview = task.prompt[:60] + ("..." if len(task.prompt) > 60 else "")
    return (
        f"[Schedule] 한 번 실행 등록 완료\n"
        f"  이름     : {task.name}\n"
        f"  시각     : {task.run_at.strftime('%Y.%m.%d %H:%M')} ({_fmt_left(task.run_at, now)})\n"
        f"  종류     : {kind}\n"
        f"  내용     : {prompt_preview}"
    )


def format_confirmation(task: "ScheduledTask", deadline: datetime) -> str:
    freq = _FREQ_LABELS.get(task.schedule, task.schedule)
    prompt_preview = task.prompt[:60] + ("..." if len(task.prompt) > 60 else "")
    return (
        f"[Schedule] 작업 등록 완료\n"
        f"  이름     : {task.name}\n"
        f"  마감     : {deadline.strftime('%Y.%m.%d %H:%M')}\n"
        f"  실행 주기: {freq}\n"
        f"  프롬프트 : {prompt_preview}"
    )


# 등록 때 한 번 호출해 알림/작업을 가른다. 실패하면 호출부가 reminder 로 둔다.
Classifier = Callable[[str], Awaitable[Literal["reminder", "task"]]]

USAGE = (
    "형식:\n"
    "  /schedule <시각>에 <내용>        — 그 시각에 한 번\n"
    "  /schedule <날짜 시각>까지 <내용>  — 마감까지 반복 실행\n"
    "예시:\n"
    "  /schedule 10분 뒤에 물 마시기\n"
    "  /schedule 오후 7시에 회의 준비 알림\n"
    "  /schedule 내일 09:00에 오늘 뉴스 요약해줘\n"
    "  /schedule 2026.06.01 오전 9시까지 웹검색으로 자료 수집해줘"
)


def make_schedule_handler(
    scheduler: "SchedulerService | None",
    classify: Classifier | None = None,
) -> "ScopedHandler":
    """SlashCommandDispatcher에 등록할 /schedule 핸들러 factory.

    classify 가 없으면 한 번 실행 항목은 모두 알림(reminder)으로 등록한다.
    """

    async def handle_once(run_at: datetime, prompt: str, agent: str) -> str:
        now = datetime.now()
        if not prompt:
            return "[Schedule] 내용이 비어 있습니다. 시각 뒤에 알릴 내용이나 할 일을 작성해주세요."
        if run_at <= now:
            return f"[Schedule] 시각({run_at.strftime('%Y.%m.%d %H:%M')})이 이미 지났습니다."
        if scheduler is None:
            return "[Schedule] 스케줄러가 비활성화 상태입니다. (JARVIS_SCHEDULER__ENABLED=true 필요)"
        kind: Literal["reminder", "task"] = "reminder"
        if classify is not None:
            try:
                kind = await classify(prompt)
            except Exception:
                kind = "reminder"
        task = build_once_task(run_at, prompt, kind).model_copy(update={"agent": agent})
        scheduler.add_task(task)
        return format_once_confirmation(task, now)

    async def handle(args: str, scope: "MemoryScope") -> str:
        """일정은 명령을 친 세션의 에이전트가 맡는다."""
        if not args.strip():
            return "[Schedule] 인자가 필요합니다.\n" + USAGE

        parsed = parse_deadline(args)
        if parsed is None:
            once = parse_once(args)
            if once is not None:
                return await handle_once(*once, scope.agent_id)
            return "[Schedule] 시각 파싱 실패.\n" + USAGE

        deadline, prompt = parsed
        if not prompt:
            return "[Schedule] 프롬프트가 비어 있습니다. 마감 시간 뒤에 실행할 작업을 작성해주세요."

        if deadline <= datetime.now():
            return f"[Schedule] 마감 시간({deadline.strftime('%Y.%m.%d %H:%M')})이 이미 지났습니다."

        if scheduler is None:
            return "[Schedule] 스케줄러가 비활성화 상태입니다. (JARVIS_SCHEDULER__ENABLED=true 필요)"

        task = build_schedule_task(deadline, prompt).model_copy(update={"agent": scope.agent_id})
        scheduler.add_task(task)
        return format_confirmation(task, deadline)

    return handle
