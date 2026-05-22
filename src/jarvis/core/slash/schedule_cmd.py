from __future__ import annotations

import re
import uuid
from datetime import datetime
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.core.scheduler.service import SchedulerService
    from jarvis.core.scheduler.task import ScheduledTask

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
    name = f"slash-{uuid.uuid4().hex[:8]}"
    return ScheduledTask(
        name=name,
        schedule=schedule,
        prompt=prompt,
        run_until=deadline,
        enabled=True,
        description=f"슬래시 명령 생성 | 마감: {deadline.strftime('%Y.%m.%d %H:%M')}",
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


def make_schedule_handler(
    scheduler: "SchedulerService | None",
) -> Callable[[str], Awaitable[str]]:
    """SlashCommandDispatcher에 등록할 /schedule 핸들러 factory."""

    async def handle(args: str) -> str:
        if not args.strip():
            return (
                "[Schedule] 인자가 필요합니다.\n"
                "형식: /schedule YYYY.MM.DD 오전/오후 N시까지 <프롬프트>\n"
                "예시: /schedule 2026.06.01 오전 9시까지 웹검색으로 자료 수집해줘"
            )

        parsed = parse_deadline(args)
        if parsed is None:
            return (
                "[Schedule] 마감 시간 파싱 실패.\n"
                "형식: /schedule YYYY.MM.DD 오전/오후 N시까지 <프롬프트>\n"
                "예시: /schedule 2026.06.01 오전 9시까지 웹검색으로 자료 수집해줘"
            )

        deadline, prompt = parsed
        if not prompt:
            return "[Schedule] 프롬프트가 비어 있습니다. 마감 시간 뒤에 실행할 작업을 작성해주세요."

        if deadline <= datetime.now():
            return f"[Schedule] 마감 시간({deadline.strftime('%Y.%m.%d %H:%M')})이 이미 지났습니다."

        if scheduler is None:
            return "[Schedule] 스케줄러가 비활성화 상태입니다. (JARVIS_SCHEDULER__ENABLED=true 필요)"

        task = build_schedule_task(deadline, prompt)
        scheduler.add_task(task)
        return format_confirmation(task, deadline)

    return handle
