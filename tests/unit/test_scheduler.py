"""SchedulerService / ScheduledTask / loader 테스트."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis.core.scheduler.task import ScheduledTask


class TestScheduledTask:
    def test_defaults(self):
        task = ScheduledTask(name="daily", schedule="0 9 * * *", prompt="Good morning")
        assert task.enabled is True
        assert task.session_id is None
        assert task.tools_allowed == []
        assert task.description == ""

    def test_full_config(self):
        task = ScheduledTask(
            name="weekly-report",
            schedule="0 8 * * 1",
            prompt="Generate weekly report",
            session_id="fixed-session",
            tools_allowed=["bash", "read_file"],
            enabled=False,
            description="Every Monday 08:00",
        )
        assert task.tools_allowed == ["bash", "read_file"]
        assert task.enabled is False
        assert task.session_id == "fixed-session"


class TestSchedulerLoader:
    def test_load_tasks_missing_dir(self, tmp_path):
        from jarvis.core.scheduler.loader import load_tasks

        tasks = load_tasks(str(tmp_path / "nonexistent"))
        assert tasks == []

    def test_load_tasks_single_yaml(self, tmp_path):
        from jarvis.core.scheduler.loader import load_tasks

        yaml_content = textwrap.dedent("""
            name: morning-brief
            schedule: "0 9 * * *"
            prompt: Give me the morning briefing
            tools_allowed:
              - web_search
        """)
        (tmp_path / "morning.yaml").write_text(yaml_content)
        tasks = load_tasks(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].name == "morning-brief"
        assert tasks[0].schedule == "0 9 * * *"
        assert "web_search" in tasks[0].tools_allowed

    def test_load_tasks_list_yaml(self, tmp_path):
        from jarvis.core.scheduler.loader import load_tasks

        yaml_content = textwrap.dedent("""
            - name: task-a
              schedule: "0 8 * * *"
              prompt: Task A
            - name: task-b
              schedule: "0 20 * * *"
              prompt: Task B
        """)
        (tmp_path / "tasks.yaml").write_text(yaml_content)
        tasks = load_tasks(str(tmp_path))
        assert len(tasks) == 2
        names = [t.name for t in tasks]
        assert "task-a" in names
        assert "task-b" in names

    def test_load_tasks_skips_invalid_yaml(self, tmp_path):
        from jarvis.core.scheduler.loader import load_tasks

        (tmp_path / "bad.yaml").write_text("not: valid: yaml: !!!")
        (tmp_path / "good.yaml").write_text("name: ok\nschedule: '0 * * * *'\nprompt: hi")
        tasks = load_tasks(str(tmp_path))
        # bad.yaml may fail validation but good.yaml should be loaded
        assert any(t.name == "ok" for t in tasks)


class TestSchedulerService:
    def _make_service(self, tasks=None):
        from jarvis.core.scheduler.service import SchedulerService
        from jarvis.core.tools.registry import ToolRegistry
        from jarvis.model_layer.types import ModelConfig

        mock_repo = MagicMock()
        mock_repo.create = AsyncMock()
        tool_registry = ToolRegistry()
        model = ModelConfig(provider="faux", model="faux-model")
        return SchedulerService(
            tasks=tasks or [],
            session_repo=mock_repo,
            tool_registry=tool_registry,
            model=model,
            base_extra={},
        )

    def test_task_count_counts_enabled_only(self):
        tasks = [
            ScheduledTask(name="a", schedule="0 * * * *", prompt="p", enabled=True),
            ScheduledTask(name="b", schedule="0 * * * *", prompt="p", enabled=False),
            ScheduledTask(name="c", schedule="0 * * * *", prompt="p", enabled=True),
        ]
        svc = self._make_service(tasks)
        assert svc.task_count == 2

    def test_add_task(self):
        svc = self._make_service()
        assert svc.task_count == 0
        svc.add_task(ScheduledTask(name="new", schedule="0 * * * *", prompt="p"))
        assert svc.task_count == 1

    async def test_start_sets_running(self):
        svc = self._make_service()
        # Patch loop to avoid actually running
        with patch.object(svc, "_loop", new_callable=AsyncMock):
            await svc.start()
            assert svc._running is True
            await svc.stop()

    async def test_start_idempotent(self):
        svc = self._make_service()
        with patch.object(svc, "_loop", new_callable=AsyncMock):
            await svc.start()
            task_handle_1 = svc._task_handle
            await svc.start()  # second call should be no-op
            assert svc._task_handle is task_handle_1
            await svc.stop()

    async def test_stop_clears_running(self):
        svc = self._make_service()
        with patch.object(svc, "_loop", new_callable=AsyncMock):
            await svc.start()
            await svc.stop()
            assert svc._running is False

    async def test_loop_skips_when_croniter_missing(self):
        """croniter 미설치 시 loop는 즉시 종료되어야 한다."""
        svc = self._make_service([
            ScheduledTask(name="t", schedule="* * * * *", prompt="p")
        ])
        with patch.dict(sys.modules, {"croniter": None}):
            await svc._loop()  # Should not raise, just print and return

    async def test_execute_task_calls_session_prompt(self):
        """_execute_task는 AgentSession.prompt()를 호출해야 한다."""
        svc = self._make_service()
        task = ScheduledTask(name="t", schedule="* * * * *", prompt="Hello scheduler")

        mock_session = MagicMock()
        mock_session.prompt = AsyncMock()

        # AgentSession is lazily imported inside _execute_task, so patch at source
        with patch("jarvis.core.session.AgentSession", return_value=mock_session):
            with patch("jarvis.agent_layer.memory.chain.MemoryMiddlewareChain"):
                with patch("jarvis.core.policy.pipeline.SecurityPipeline"):
                    await svc._execute_task(task)

        mock_session.prompt.assert_called_once_with("Hello scheduler")


class TestSchedulerConfig:
    def test_scheduler_config_defaults(self, monkeypatch):
        monkeypatch.delenv("JARVIS_SCHEDULER__ENABLED", raising=False)
        monkeypatch.delenv("JARVIS_SCHEDULER__SCHEDULES_DIR", raising=False)
        from jarvis.config import SchedulerConfig

        cfg = SchedulerConfig()
        assert cfg.enabled is True
        assert "schedules" in cfg.schedules_dir

    def test_scheduler_in_jarvis_settings(self):
        from jarvis.config import JarvisSettings
        s = JarvisSettings()
        assert hasattr(s, "scheduler")
        assert s.scheduler.enabled is True


# ── 목록·토글·저장 (HUD Agenda) ──────────────────────────────────────────────


def _service(tasks=None, schedules_dir=None):
    from jarvis.core.scheduler.service import SchedulerService

    return SchedulerService(
        tasks=tasks or [],
        session_repo=MagicMock(),
        tool_registry=MagicMock(),
        model=MagicMock(),
        base_extra={},
        schedules_dir=schedules_dir,
    )


class TestSchedulerAgenda:
    def test_list_tasks_includes_disabled_and_is_a_copy(self):
        tasks = [
            ScheduledTask(name="a", schedule="0 * * * *", prompt="p"),
            ScheduledTask(name="b", schedule="0 * * * *", prompt="p", enabled=False),
        ]
        svc = _service(tasks)
        listed = svc.list_tasks()
        assert [t.name for t in listed] == ["a", "b"]
        listed.clear()
        assert len(svc.list_tasks()) == 2

    def test_set_enabled_unknown_name_returns_false(self):
        assert _service().set_enabled("nope", False) is False

    def test_toggle_rewrites_only_enabled_in_source_yaml(self, tmp_path):
        """사용자가 쓴 파일에서는 enabled 키만 바뀌고 나머지 필드는 남아야 한다."""
        import yaml

        from jarvis.core.scheduler.loader import load_tasks

        path = tmp_path / "brief.yaml"
        path.write_text(textwrap.dedent("""
            name: brief
            schedule: "0 9 * * *"
            prompt: morning brief
            description: 매일 아침
            tools_allowed: [web_search]
        """))
        svc = _service(load_tasks(str(tmp_path)), schedules_dir=str(tmp_path))

        assert svc.set_enabled("brief", False) is True
        data = yaml.safe_load(path.read_text())
        assert data["enabled"] is False
        assert data["description"] == "매일 아침"
        assert data["tools_allowed"] == ["web_search"]
        # 재시작해도 꺼진 상태가 남는다
        assert load_tasks(str(tmp_path))[0].enabled is False

    def test_toggle_in_list_file_touches_only_matching_item(self, tmp_path):
        import yaml

        from jarvis.core.scheduler.loader import load_tasks

        path = tmp_path / "many.yaml"
        path.write_text(textwrap.dedent("""
            - name: one
              schedule: "0 9 * * *"
              prompt: p1
            - name: two
              schedule: "0 10 * * *"
              prompt: p2
        """))
        svc = _service(load_tasks(str(tmp_path)), schedules_dir=str(tmp_path))
        svc.set_enabled("two", False)

        items = yaml.safe_load(path.read_text())
        assert [i["name"] for i in items] == ["one", "two"]
        assert "enabled" not in items[0]
        assert items[1]["enabled"] is False

    def test_toggle_is_idempotent(self, tmp_path):
        from jarvis.core.scheduler.loader import load_tasks

        path = tmp_path / "brief.yaml"
        path.write_text('name: brief\nschedule: "0 9 * * *"\nprompt: p\n')
        svc = _service(load_tasks(str(tmp_path)), schedules_dir=str(tmp_path))
        svc.set_enabled("brief", False)
        first = path.read_text()
        svc.set_enabled("brief", False)
        assert path.read_text() == first

    def test_added_task_is_saved_and_survives_restart(self, tmp_path):
        """/schedule 로 만든 작업이 재시작 후에도 남아야 한다."""
        from datetime import datetime, timedelta

        from jarvis.core.scheduler.loader import load_tasks

        deadline = datetime.now().replace(microsecond=0) + timedelta(days=3)
        svc = _service(schedules_dir=str(tmp_path))
        svc.add_task(ScheduledTask(name="slash-1", schedule="0 * * * *", prompt="collect", run_until=deadline))

        assert (tmp_path / "slash-1.yaml").exists()
        reloaded = load_tasks(str(tmp_path))
        assert [t.name for t in reloaded] == ["slash-1"]
        assert reloaded[0].run_until == deadline

        # 저장된 작업을 끄면 같은 파일에 반영된다
        svc.set_enabled("slash-1", False)
        assert load_tasks(str(tmp_path))[0].enabled is False

    def test_add_task_without_dir_stays_in_memory(self, tmp_path):
        svc = _service()
        svc.add_task(ScheduledTask(name="mem", schedule="0 * * * *", prompt="p"))
        assert list(tmp_path.iterdir()) == []


class TestSchedulerNextRun:
    def setup_method(self):
        pytest.importorskip("croniter")

    def test_next_run_follows_cron(self):
        from datetime import datetime

        from jarvis.core.scheduler.service import SchedulerService

        task = ScheduledTask(name="t", schedule="0 9 * * *", prompt="p")
        nxt = SchedulerService.next_run(task, datetime(2026, 9, 24, 8, 30))
        assert nxt == datetime(2026, 9, 24, 9, 0)

    def test_disabled_task_has_no_next_run(self):
        from jarvis.core.scheduler.service import SchedulerService

        task = ScheduledTask(name="t", schedule="0 9 * * *", prompt="p", enabled=False)
        assert SchedulerService.next_run(task) is None

    def test_next_run_after_deadline_is_none(self):
        from datetime import datetime

        from jarvis.core.scheduler.service import SchedulerService

        task = ScheduledTask(
            name="t", schedule="0 9 * * *", prompt="p", run_until=datetime(2026, 9, 24, 8, 45),
        )
        assert SchedulerService.next_run(task, datetime(2026, 9, 24, 8, 30)) is None

    def test_bad_cron_has_no_next_run(self):
        from jarvis.core.scheduler.service import SchedulerService

        task = ScheduledTask(name="t", schedule="not a cron", prompt="p")
        assert SchedulerService.next_run(task) is None
