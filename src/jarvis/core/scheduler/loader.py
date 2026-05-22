from __future__ import annotations

from pathlib import Path

import yaml

from jarvis.core.scheduler.task import ScheduledTask


def load_tasks(schedules_dir: str) -> list[ScheduledTask]:
    """지정 디렉토리의 모든 *.yaml 파일에서 ScheduledTask 목록을 로딩한다."""
    root = Path(schedules_dir).expanduser()
    if not root.exists():
        return []

    tasks: list[ScheduledTask] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                task = ScheduledTask.model_validate(data)
                tasks.append(task)
            elif isinstance(data, list):
                for item in data:
                    tasks.append(ScheduledTask.model_validate(item))
        except Exception as exc:
            print(f"[SchedulerLoader] Failed to load '{path}': {exc}")
    return tasks
