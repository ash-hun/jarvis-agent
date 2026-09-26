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
                task._source = path
                tasks.append(task)
            elif isinstance(data, list):
                for item in data:
                    task = ScheduledTask.model_validate(item)
                    task._source = path
                    tasks.append(task)
        except Exception as exc:
            print(f"[SchedulerLoader] Failed to load '{path}': {exc}")
    return tasks


def save_task(task: ScheduledTask, schedules_dir: str) -> Path:
    """작업을 `<schedules_dir>/<name>.yaml` 로 저장한다. 같은 작업을 다시 저장해도 결과가 같다.

    항상 작업 전용 파일에만 쓴다 — 여러 작업이 든 사용자 YAML 을 통째로 덮어쓰지 않도록
    `_source` 를 따라가지 않는다(기존 파일의 토글은 write_enabled 가 맡는다).
    """
    root = Path(schedules_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{task.name}.yaml"
    data = task.model_dump(mode="json", exclude_none=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    task._source = path
    return path


def write_enabled(task: ScheduledTask) -> bool:
    """원본 YAML 에서 이 작업의 `enabled` 키만 바꿔 되쓴다.

    사용자가 손으로 쓴 다른 필드는 그대로 둔다. 파일 하나에 작업 목록이 들어 있으면
    이름이 같은 항목만 고친다. 원본 파일이 없거나 항목을 못 찾으면 False.
    """
    path = task._source
    if path is None or not path.exists():
        return False
    with open(path) as f:
        data = yaml.safe_load(f)
    items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
    target = next((i for i in items if isinstance(i, dict) and i.get("name") == task.name), None)
    if target is None:
        return False
    target["enabled"] = task.enabled
    with open(path, "w") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return True


def remove_task_file(task: ScheduledTask, schedules_dir: str | None) -> None:
    """실행을 마친 한 번 실행 작업의 저장 파일을 치운다.

    우리가 만든 작업 전용 파일(<dir>/<name>.yaml)이면 지우고, 사용자가 쓴 파일이면
    지우지 않고 enabled: false 로만 바꾼다(손으로 쓴 내용을 날리지 않게).
    """
    path = task._source
    if path is None and schedules_dir:
        candidate = Path(schedules_dir).expanduser() / f"{task.name}.yaml"
        path = candidate if candidate.exists() else None
    if path is None or not path.exists():
        return
    if path.name == f"{task.name}.yaml":
        with open(path) as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and data.get("name") == task.name:
            path.unlink()
            return
    task.enabled = False
    write_enabled(task)
