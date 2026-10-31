"""scheduler 의 YAML 로더: 작업 읽기, 잘못된 파일 건너뛰기, 사용자가 쓴 한 번 실행 파일은 끄기만 한다."""

import yaml
import pytest
import textwrap

from jarvis.core.scheduler.scheduler_loader import load_tasks, remove_task_file


def test_load_tasks_missing_dir_returns_empty(tmp_path):
    assert load_tasks(str(tmp_path / "nonexistent")) == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            """
            name: morning-brief
            schedule: "0 9 * * *"
            prompt: Give me the morning briefing
            tools_allowed:
              - web_search
            """,
            {"morning-brief": ("0 9 * * *", ["web_search"])},
        ),
        (
            """
            - name: task-a
              schedule: "0 8 * * *"
              prompt: Task A
            - name: task-b
              schedule: "0 20 * * *"
              prompt: Task B
            """,
            {"task-a": ("0 8 * * *", []), "task-b": ("0 20 * * *", [])},
        ),
    ],
    ids=["single", "list"],
)
def test_load_tasks_reads_single_or_list_yaml(tmp_path, content, expected):
    (tmp_path / "tasks.yaml").write_text(textwrap.dedent(content))

    tasks = load_tasks(str(tmp_path))

    assert {t.name: (t.schedule, t.tools_allowed) for t in tasks} == expected


def test_load_tasks_skips_invalid_file_and_keeps_good_one(tmp_path):
    (tmp_path / "bad.yaml").write_text("not: valid: yaml: !!!")
    (tmp_path / "good.yaml").write_text("name: ok\nschedule: '0 * * * *'\nprompt: hi")

    tasks = load_tasks(str(tmp_path))

    assert any(t.name == "ok" for t in tasks)


def test_remove_task_file_disables_user_authored_once_item_without_deleting(tmp_path):
    path = tmp_path / "mine.yaml"
    path.write_text(
        '- name: a\n  prompt: p\n  run_at: "2026-09-24T19:00:00"\n'
        '- name: b\n  schedule: "0 9 * * *"\n  prompt: q\n'
    )
    task = load_tasks(str(tmp_path))[0]

    remove_task_file(task, str(tmp_path))

    items = yaml.safe_load(path.read_text())
    assert path.exists() and items[0]["enabled"] is False and "enabled" not in items[1]
