"""SchedulerService / ScheduledTask / loader 테스트."""
import sys
import pytest
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.core.scheduler.task import ScheduledTask
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local")


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

    async def test_loop_without_croniter_does_not_raise(self):
        """croniter 미설치여도 loop 가 예외 없이 돈다(cron 작업만 건너뛰고 한 번 실행 작업은 처리)."""
        svc = self._make_service([
            ScheduledTask(name="t", schedule="* * * * *", prompt="p")
        ])
        with patch.dict(sys.modules, {"croniter": None}):
            await svc._loop()  # _running 이 False 라 바로 끝난다 — ImportError 만 없으면 된다
        assert svc._tick(__import__("datetime").datetime.now(), None) == []  # cron 작업은 건너뜀

    async def test_execute_task_calls_session_prompt(self):
        """_execute_task는 AgentSession.prompt()를 호출해야 한다."""
        svc = self._make_service()
        task = ScheduledTask(name="t", schedule="* * * * *", prompt="Hello scheduler")

        mock_session = MagicMock()
        mock_session.prompt = AsyncMock()

        # AgentSession is lazily imported inside _execute_task, so patch at source
        with patch("jarvis.core.session.AgentSession", return_value=mock_session):
            with patch("jarvis.core.policy.pipeline.SecurityPipeline"):
                await svc._execute_task(task)

        mock_session.prompt.assert_called_once_with("Hello scheduler")


    async def test_execute_task_runs_as_its_agent(self):
        """agent 가 main 이 아니면 그 에이전트의 모델, 시스템 프롬프트, 이름으로 세션을 만든다."""
        from jarvis.core.scheduler.service import TaskAgent

        svc = self._make_service()
        karen_model = MagicMock()
        svc.set_agent_resolver(lambda a: TaskAgent(karen_model, "카렌", "karen") if a == "karen" else None)
        task = ScheduledTask(name="k", schedule="* * * * *", prompt="뉴스", agent="karen")
        mock_session = MagicMock()
        mock_session.prompt = AsyncMock()

        with patch("jarvis.core.session.AgentSession", return_value=mock_session) as ctor:
            with patch("jarvis.core.policy.pipeline.SecurityPipeline"):
                await svc._execute_task(task)

        kwargs = ctor.call_args.kwargs
        assert (kwargs["model"], kwargs["system_prompt"], kwargs["agent_name"]) == (karen_model, "카렌", "karen")
        assert svc._session_repo.create.call_args.kwargs["agent_id"] == "karen"

    async def test_execute_task_with_unknown_agent_fails_without_running(self):
        svc = self._make_service()
        task = ScheduledTask(name="g", schedule="* * * * *", prompt="x", agent="ghost")
        with patch("jarvis.core.session.AgentSession") as ctor:
            assert await svc._execute_task(task) is None
        ctor.assert_not_called()


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


# ── 한 번 실행 알림 (/schedule ~에) ──────────────────────────────────────────


class TestParseOnce:
    def setup_method(self):
        from datetime import datetime

        self.now = datetime(2026, 9, 24, 18, 57, 30)

    def _parse(self, text, now=None):
        from jarvis.core.slash.schedule_cmd import parse_once

        return parse_once(text, now or self.now)

    def test_relative_minutes(self):
        from datetime import timedelta

        at, prompt = self._parse("3분 뒤에 물 마시기")
        assert at == (self.now + timedelta(minutes=3)).replace(microsecond=0)
        assert prompt == "물 마시기"

    def test_relative_hours_without_particle(self):
        from datetime import timedelta

        at, prompt = self._parse("1시간 후 스트레칭")
        assert at == self.now + timedelta(hours=1)
        assert prompt == "스트레칭"

    def test_ampm_today_when_still_ahead(self):
        from datetime import datetime

        at, prompt = self._parse("오후 7시에 알림 하나줘.")
        assert at == datetime(2026, 9, 24, 19, 0)
        assert prompt == "알림 하나줘."

    def test_time_already_passed_without_day_rolls_to_tomorrow(self):
        from datetime import datetime

        at, _ = self._parse("오후 6시에 퇴근")
        assert at == datetime(2026, 9, 25, 18, 0)

    def test_tomorrow_with_minutes(self):
        from datetime import datetime

        at, prompt = self._parse("내일 오전 9시 30분에 오늘 뉴스 요약해줘")
        assert at == datetime(2026, 9, 25, 9, 30)
        assert prompt == "오늘 뉴스 요약해줘"

    def test_24h_clock(self):
        from datetime import datetime

        at, _ = self._parse("19:05에 회의")
        assert at == datetime(2026, 9, 24, 19, 5)

    def test_full_date(self):
        from datetime import datetime

        at, _ = self._parse("2026.10.01 오후 7시에 보고서")
        assert at == datetime(2026, 10, 1, 19, 0)

    def test_until_is_not_once(self):
        assert self._parse("2026.10.01 오후 7시까지 자료 수집") is None


class TestScheduleOnceHandler:
    def _scheduler(self):
        s = MagicMock()
        s.add_task = MagicMock()
        return s

    async def test_registers_once_task_with_classified_kind(self):
        from jarvis.core.slash.schedule_cmd import make_schedule_handler

        scheduler = self._scheduler()
        classify = AsyncMock(return_value="task")
        scope = MemoryScope(user_id="local", agent_id="karen")
        out = await make_schedule_handler(scheduler, classify)("10분 뒤에 오늘 뉴스 요약해줘", scope)

        task = scheduler.add_task.call_args[0][0]
        assert task.run_at is not None and task.schedule == ""
        assert task.agent == "karen"  # 명령을 친 세션의 에이전트가 맡는다
        assert task.kind == "task"
        assert task.prompt == "오늘 뉴스 요약해줘"
        classify.assert_awaited_once_with("오늘 뉴스 요약해줘")
        assert "한 번 실행 등록 완료" in out and "작업" in out

    async def test_without_classifier_defaults_to_reminder(self):
        from jarvis.core.slash.schedule_cmd import make_schedule_handler

        scheduler = self._scheduler()
        await make_schedule_handler(scheduler)("5분 뒤에 물 마시기", SCOPE)
        assert scheduler.add_task.call_args[0][0].kind == "reminder"

    async def test_classifier_failure_falls_back_to_reminder(self):
        from jarvis.core.slash.schedule_cmd import make_schedule_handler

        scheduler = self._scheduler()
        classify = AsyncMock(side_effect=RuntimeError("llm down"))
        await make_schedule_handler(scheduler, classify)("5분 뒤에 물 마시기", SCOPE)
        assert scheduler.add_task.call_args[0][0].kind == "reminder"

    async def test_past_time_rejected(self):
        from jarvis.core.slash.schedule_cmd import make_schedule_handler

        scheduler = self._scheduler()
        out = await make_schedule_handler(scheduler)("2020.01.01 오전 9시에 x", SCOPE)
        assert "이미 지났" in out
        scheduler.add_task.assert_not_called()


class TestSchedulerOnceFiring:
    def _svc(self, tasks, tmp_path=None):
        svc = _service(tasks, schedules_dir=str(tmp_path) if tmp_path else None)
        svc.set_notifier(AsyncMock())
        return svc

    async def test_due_reminder_is_delivered_once_and_removed(self, tmp_path):
        import asyncio
        from datetime import datetime, timedelta

        now = datetime(2026, 9, 24, 19, 0, 4)
        svc = self._svc([], tmp_path)
        svc.add_task(ScheduledTask(name="once-1", prompt="물 마시기", kind="reminder",
                                   run_at=now - timedelta(seconds=4)))
        assert (tmp_path / "once-1.yaml").exists()

        await asyncio.gather(*svc._tick(now, None))
        payload = svc._notify.await_args[0][0]
        assert payload["type"] == "reminder" and payload["text"] == "물 마시기"
        assert payload["kind"] == "reminder" and payload["once"] is True
        assert payload["delayed_sec"] == 4
        # 목록·파일에서 사라져 다시 울리지 않는다
        assert svc.list_tasks() == []
        assert not (tmp_path / "once-1.yaml").exists()
        assert svc._tick(now + timedelta(seconds=10), None) == []

    def test_future_once_task_is_not_fired(self):
        from datetime import datetime, timedelta

        now = datetime(2026, 9, 24, 18, 0)
        svc = self._svc([ScheduledTask(name="later", prompt="p", run_at=now + timedelta(minutes=5))])
        assert svc._tick(now, None) == []
        assert svc.next_run(svc.get_task("later")) == now + timedelta(minutes=5)

    async def test_overdue_after_restart_reports_delay(self):
        import asyncio
        from datetime import datetime, timedelta

        now = datetime(2026, 9, 24, 19, 30)
        svc = self._svc([ScheduledTask(name="missed", prompt="p", kind="reminder",
                                       run_at=now - timedelta(minutes=30))])
        await asyncio.gather(*svc._tick(now, None))
        assert svc._notify.await_args[0][0]["delayed_sec"] == 1800

    async def test_task_kind_delivers_agent_answer(self):
        import asyncio
        from datetime import datetime

        now = datetime(2026, 9, 24, 19, 0)
        svc = self._svc([ScheduledTask(name="news", prompt="뉴스 요약", kind="task", run_at=now)])
        with patch.object(svc, "_execute_task", AsyncMock(return_value="오늘의 요약")):
            await asyncio.gather(*svc._tick(now, None))
        payload = svc._notify.await_args[0][0]
        assert payload["text"] == "오늘의 요약" and payload["error"] is False

    async def test_failed_task_is_reported_as_error(self):
        import asyncio
        from datetime import datetime

        now = datetime(2026, 9, 24, 19, 0)
        svc = self._svc([ScheduledTask(name="news", prompt="뉴스 요약", kind="task", run_at=now)])
        with patch.object(svc, "_execute_task", AsyncMock(return_value=None)):
            await asyncio.gather(*svc._tick(now, None))
        assert svc._notify.await_args[0][0]["error"] is True

    async def test_cron_task_result_is_delivered_too(self):
        import asyncio
        from datetime import datetime

        croniter = pytest.importorskip("croniter").croniter
        now = datetime(2026, 9, 24, 9, 0, 5)
        svc = self._svc([ScheduledTask(name="brief", schedule="0 9 * * *", prompt="브리핑")])
        with patch.object(svc, "_execute_task", AsyncMock(return_value="브리핑 내용")):
            await asyncio.gather(*svc._tick(now, croniter))
        payload = svc._notify.await_args[0][0]
        assert payload["once"] is False and payload["text"] == "브리핑 내용"

    async def test_cron_slot_fires_once_across_ticks(self):
        import asyncio
        from datetime import datetime, timedelta

        croniter = pytest.importorskip("croniter").croniter
        slot = datetime(2026, 9, 24, 9, 0, 0)
        svc = self._svc([ScheduledTask(name="brief", schedule="0 9 * * *", prompt="브리핑")])
        with patch.object(svc, "_execute_task", AsyncMock(return_value="x")):
            await asyncio.gather(*svc._tick(slot + timedelta(seconds=5), croniter))
            await asyncio.gather(*svc._tick(slot + timedelta(seconds=15), croniter))
            await asyncio.gather(*svc._tick(slot + timedelta(seconds=70), croniter))
        assert svc._notify.await_count == 1

    def test_user_authored_once_file_is_disabled_not_deleted(self, tmp_path):
        import yaml

        from jarvis.core.scheduler.loader import load_tasks, remove_task_file

        path = tmp_path / "mine.yaml"
        path.write_text(
            '- name: a\n  prompt: p\n  run_at: "2026-09-24T19:00:00"\n'
            '- name: b\n  schedule: "0 9 * * *"\n  prompt: q\n'
        )
        task = load_tasks(str(tmp_path))[0]
        remove_task_file(task, str(tmp_path))
        items = yaml.safe_load(path.read_text())
        assert path.exists() and items[0]["enabled"] is False and "enabled" not in items[1]


class TestToolTask:
    """kind: tool 은 LLM 없이 도구를 바로 부르고, 빈 글이면 알리지 않는다."""

    def _service(self, tool):
        from jarvis.core.scheduler.service import SchedulerService, TaskAgent
        from jarvis.core.tools.registry import ToolRegistry

        agent_tools = ToolRegistry()
        agent_tools.register(tool)
        svc = SchedulerService(tasks=[], session_repo=MagicMock(), tool_registry=ToolRegistry(), model=MagicMock())
        svc.set_agent_resolver(lambda a: TaskAgent(MagicMock(), None, "karen", agent_tools) if a == "karen" else None)
        sent: list[dict] = []

        async def notify(payload):
            sent.append(payload)

        svc.set_notifier(notify)
        return svc, sent

    def _tool(self, texts: list[str], error: bool = False):
        from jarvis.model_layer.types import TextContent, ToolResultMessage
        from jarvis.core.tools.registry import JarvisTool

        class Echo(JarvisTool):
            name = "housing_watch"
            description = "x"
            parameters = {"type": "object", "properties": {}}
            calls: list[dict] = []

            async def execute(self, tool_call_id, params, signal=None, context=None):
                Echo.calls.append({"params": params, "agent": context.scope.agent_id})
                return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name,
                                         content=[TextContent(text=texts.pop(0))], is_error=error)

        return Echo()

    async def test_runs_the_agents_tool_and_skips_empty_text(self):
        tool = self._tool(["", "새 LH 공고 1건"])
        svc, sent = self._service(tool)
        task = ScheduledTask(name="watch", schedule="0 9 * * *", prompt="", kind="tool", tool="housing_watch",
                             args={"regions": "서울", "quiet": True}, agent="karen", description="새 공고")
        await svc._run_and_deliver(task)
        assert sent == []
        await svc._run_and_deliver(task)
        assert [p["text"] for p in sent] == ["새 LH 공고 1건"] and sent[0]["label"] == "watch"
        assert tool.calls[0] == {"params": {"regions": "서울", "quiet": True}, "agent": "karen"}

    async def test_tool_error_or_unknown_tool_is_a_failed_notice(self):
        svc, sent = self._service(self._tool(["LH 조회 실패"], error=True))
        await svc._run_and_deliver(ScheduledTask(name="w", prompt="", kind="tool", tool="housing_watch", agent="karen"))
        await svc._run_and_deliver(ScheduledTask(name="g", prompt="", kind="tool", tool="ghost", agent="karen"))
        assert [p["error"] for p in sent] == [True, True]

    async def test_conversation_delivery_goes_to_the_agent_and_falls_back_to_a_notice(self):
        """deliver: conversation 이면 에이전트의 대화로 건네고, 건넬 대화가 없으면 스케줄 알림으로 보낸다."""
        svc, sent = self._service(self._tool(["애쉬, 새로 올라온 공고가 1건 있어요", "애쉬, 새 공고 2건", "실패", ""]))
        spoken: list[tuple[str, str]] = []
        joined = [True, False]

        async def converse(agent, text):
            spoken.append((agent, text))
            return joined.pop(0)

        svc.set_conversation(converse)
        task = ScheduledTask(name="rt", prompt="", kind="tool", tool="housing_watch", agent="karen",
                             deliver="conversation")
        await svc._run_and_deliver(task)
        assert spoken == [("karen", "애쉬, 새로 올라온 공고가 1건 있어요")] and sent == []
        await svc._run_and_deliver(task)
        assert [p["text"] for p in sent] == ["애쉬, 새 공고 2건"]
        # 새 공고가 없으면(빈 글) 어디에도 보내지 않는다
        await svc._run_and_deliver(task.model_copy(update={"deliver": "notice"}))
        await svc._run_and_deliver(task)
        assert len(spoken) == 2 and len(sent) == 2
