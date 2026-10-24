"""[core] 스케줄된 작업 하나의 정의(YAML 또는 /schedule 명령으로 생성)."""

from pathlib import Path
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, PrivateAttr

from jarvis.memory.scope import MAIN_AGENT

# /schedule 이 사람 대신 붙이는 이름의 머리. 이런 이름은 알림 제목으로 보이지 않는다
ONCE_PREFIX = "once-"
SLASH_PREFIX = "slash-"
AUTO_NAME_PREFIXES = (ONCE_PREFIX, SLASH_PREFIX)
REMINDER_LABEL = "알림"


class ScheduledTask(BaseModel):
    """스케줄된 작업 정의. ~/.jarvis/schedules/*.yaml 또는 /schedule 슬래시 명령으로 생성."""

    name: str
    schedule: str = ""  # cron expression: "0 9 * * *". 한 번 실행(run_at) 작업은 비어 있다
    prompt: str
    session_id: str | None = None  # None = 실행마다 새 세션
    tools_allowed: list[str] = Field(default_factory=list)  # 빈 리스트 = 전체 허용
    enabled: bool = True
    description: str = ""
    run_until: datetime | None = None  # 이 시각 이후 자동 만료 (슬래시 명령용)
    run_at: datetime | None = None  # 설정되면 cron 대신 이 시각에 한 번 실행하고 사라진다
    # reminder: 정한 시각에 prompt 문구를 그대로 알린다(LLM 호출 없음)
    # task: prompt 를 에이전트가 실행하고 그 답을 알린다
    # tool: tool 을 args 로 바로 부르고 그 글을 알린다(LLM 호출 없음). 글이 비면 알리지 않는다
    kind: Literal["reminder", "task", "tool"] = "task"
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    # 작업을 실행할 최상위 에이전트 id. 그 에이전트의 모델과 시스템 프롬프트, 기억 범위로 돈다
    agent: str = MAIN_AGENT

    # 이 작업을 읽어 온(또는 저장한) YAML 파일. 토글을 원본 파일에 되쓰는 데 쓴다.
    # 직렬화 대상이 아니다. None 이면 아직 파일이 없는 메모리 전용 작업.
    _source: Path | None = PrivateAttr(default=None)


def task_label(task: ScheduledTask) -> str:
    """알림 제목. 사람이 붙인 이름이면 그 이름, /schedule 이 붙인 이름이면 알림은 "알림", 작업은 할 일 첫 줄."""
    if not task.name.startswith(AUTO_NAME_PREFIXES):
        return task.name
    if task.kind == "reminder":
        return REMINDER_LABEL
    if task.kind == "tool":
        return task.description or task.tool
    return task.prompt.strip().splitlines()[0][:80] if task.prompt.strip() else REMINDER_LABEL
