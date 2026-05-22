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
