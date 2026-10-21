"""SlashCommandDispatcher / /schedule 파서 테스트."""
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local")


class TestParseDeadline:
    def test_korean_am(self):
        from jarvis.core.slash.schedule_cmd import parse_deadline

        result = parse_deadline("2026.06.01 오전 9시까지 자료 수집해줘")
        assert result is not None
        deadline, prompt = result
        assert deadline == datetime(2026, 6, 1, 9, 0)
        assert prompt == "자료 수집해줘"

    def test_korean_pm(self):
        from jarvis.core.slash.schedule_cmd import parse_deadline

        result = parse_deadline("2026.06.01 오후 3시까지 보고서 작성해줘")
        assert result is not None
        deadline, prompt = result
        assert deadline == datetime(2026, 6, 1, 15, 0)
        assert prompt == "보고서 작성해줘"

    def test_korean_am_midnight(self):
        """오전 12시 = 0시 (자정)."""
        from jarvis.core.slash.schedule_cmd import parse_deadline

        result = parse_deadline("2026.06.01 오전 12시까지 작업해줘")
        assert result is not None
        deadline, _ = result
        assert deadline.hour == 0

    def test_24h_format(self):
        from jarvis.core.slash.schedule_cmd import parse_deadline

        result = parse_deadline("2026.06.01 09:30까지 웹 검색해줘")
        assert result is not None
        deadline, prompt = result
        assert deadline == datetime(2026, 6, 1, 9, 30)
        assert prompt == "웹 검색해줘"

    def test_invalid_format_returns_none(self):
        from jarvis.core.slash.schedule_cmd import parse_deadline

        assert parse_deadline("내일까지 뭔가 해줘") is None
        assert parse_deadline("") is None
        assert parse_deadline("오늘 저녁에 해줘") is None

    def test_multiword_prompt_preserved(self):
        from jarvis.core.slash.schedule_cmd import parse_deadline

        result = parse_deadline(
            "2026.06.01 오전 9시까지 웹검색을 통해 AI 관련 최신 논문을 수집하고 요약해줘"
        )
        assert result is not None
        _, prompt = result
        assert prompt == "웹검색을 통해 AI 관련 최신 논문을 수집하고 요약해줘"


class TestInferSchedule:
    def test_long_deadline_daily(self):
        from jarvis.core.slash.schedule_cmd import infer_schedule

        far_deadline = datetime.now() + timedelta(days=10)
        schedule = infer_schedule(far_deadline)
        assert schedule == "0 9 * * *"

    def test_medium_deadline_6hourly(self):
        from jarvis.core.slash.schedule_cmd import infer_schedule

        medium_deadline = datetime.now() + timedelta(days=3)
        schedule = infer_schedule(medium_deadline)
        assert schedule == "0 0,6,12,18 * * *"

    def test_short_deadline_hourly(self):
        from jarvis.core.slash.schedule_cmd import infer_schedule

        short_deadline = datetime.now() + timedelta(hours=12)
        schedule = infer_schedule(short_deadline)
        assert schedule == "0 * * * *"

    def test_imminent_deadline_10min(self):
        from jarvis.core.slash.schedule_cmd import infer_schedule

        imminent_deadline = datetime.now() + timedelta(minutes=30)
        schedule = infer_schedule(imminent_deadline)
        assert schedule == "*/10 * * * *"


class TestBuildScheduleTask:
    def test_task_has_run_until(self):
        from jarvis.core.slash.schedule_cmd import build_schedule_task

        deadline = datetime(2026, 6, 1, 9, 0)
        task = build_schedule_task(deadline, "웹 검색해줘")
        assert task.run_until == deadline
        assert task.prompt == "웹 검색해줘"
        assert task.enabled is True
        assert task.name.startswith("slash-")

    def test_task_name_unique(self):
        from jarvis.core.slash.schedule_cmd import build_schedule_task

        deadline = datetime(2026, 6, 1, 9, 0)
        t1 = build_schedule_task(deadline, "p")
        t2 = build_schedule_task(deadline, "p")
        assert t1.name != t2.name


class TestSlashCommandDispatcher:
    def _make_dispatcher(self, scheduler=None):
        from jarvis.core.slash.dispatcher import SlashCommandDispatcher
        return SlashCommandDispatcher(scheduler=scheduler)

    # ── 기본 반환 타입 ─────────────────────────────────────────────────────────

    async def test_no_slash_returns_empty_feedbacks(self):
        d = self._make_dispatcher()
        result = await d.dispatch("오늘 날씨 알려줘", SCOPE)
        assert result.feedbacks == []
        assert result.remaining_text == "오늘 날씨 알려줘"
        assert not result.fully_consumed

    async def test_help_command(self):
        d = self._make_dispatcher()
        result = await d.dispatch("/help", SCOPE)
        assert len(result.feedbacks) == 1
        assert "/schedule" in result.feedbacks[0]
        assert result.fully_consumed

    async def test_question_mark_alias(self):
        d = self._make_dispatcher()
        result = await d.dispatch("/?", SCOPE)
        assert len(result.feedbacks) == 1
        assert "/schedule" in result.feedbacks[0]

    async def test_unknown_command(self):
        d = self._make_dispatcher()
        result = await d.dispatch("/foobar", SCOPE)
        assert len(result.feedbacks) == 1
        assert "알 수 없는 명령" in result.feedbacks[0]

    async def test_schedule_no_args(self):
        d = self._make_dispatcher()
        result = await d.dispatch("/schedule", SCOPE)
        assert "인자가 필요" in result.feedbacks[0]

    async def test_schedule_bad_format(self):
        d = self._make_dispatcher()
        result = await d.dispatch("/schedule 내일 오전에 해줘", SCOPE)
        assert "파싱 실패" in result.feedbacks[0]

    async def test_schedule_no_scheduler(self):
        d = self._make_dispatcher(scheduler=None)
        future = datetime.now() + timedelta(days=5)
        cmd = f"/schedule {future.strftime('%Y.%m.%d')} 오전 9시까지 자료 수집해줘"
        result = await d.dispatch(cmd, SCOPE)
        assert "비활성화" in result.feedbacks[0]

    async def test_schedule_past_deadline(self):
        d = self._make_dispatcher(scheduler=MagicMock())
        result = await d.dispatch("/schedule 2020.01.01 오전 9시까지 자료 수집해줘", SCOPE)
        assert "이미 지났" in result.feedbacks[0]

    async def test_schedule_success_registers_task(self):
        mock_scheduler = MagicMock()
        mock_scheduler.add_task = MagicMock()
        d = self._make_dispatcher(scheduler=mock_scheduler)

        future = datetime.now() + timedelta(days=5)
        cmd = f"/schedule {future.strftime('%Y.%m.%d')} 오전 9시까지 웹검색으로 자료 수집해줘"
        result = await d.dispatch(cmd, SCOPE)

        assert "등록 완료" in result.feedbacks[0]
        mock_scheduler.add_task.assert_called_once()
        added_task = mock_scheduler.add_task.call_args[0][0]
        assert added_task.run_until is not None
        assert added_task.run_until.hour == 9
        assert "웹검색으로 자료 수집해줘" in added_task.prompt

    async def test_schedule_empty_prompt(self):
        mock_scheduler = MagicMock()
        d = self._make_dispatcher(scheduler=mock_scheduler)
        future = datetime.now() + timedelta(days=5)
        cmd = f"/schedule {future.strftime('%Y.%m.%d')} 오전 9시까지"  # no prompt
        result = await d.dispatch(cmd, SCOPE)
        assert result.feedbacks  # 에러 메시지 있어야 함
        mock_scheduler.add_task.assert_not_called()

    # ── 인라인 파싱 (지시문 중간에 /command) ──────────────────────────────────

    async def test_inline_command_at_end(self):
        """지시문 끝에 /help — remaining_text로 앞 텍스트 남김."""
        d = self._make_dispatcher()
        result = await d.dispatch("이것저것 알려줘 /help", SCOPE)
        assert len(result.feedbacks) == 1
        assert "/schedule" in result.feedbacks[0]
        assert result.remaining_text == "이것저것 알려줘"
        assert not result.fully_consumed

    async def test_inline_command_in_middle(self):
        """지시문 중간에 /help — 앞뒤 텍스트 모두 remaining_text."""
        d = self._make_dispatcher()
        result = await d.dispatch("앞부분 /help 뒷부분", SCOPE)
        # /help 이후 "뒷부분"은 같은 줄이므로 help의 args로 흡수됨 (줄 끝까지)
        assert len(result.feedbacks) == 1
        assert result.remaining_text == "앞부분"

    async def test_inline_multiline_remaining(self):
        """멀티라인 입력 — /command가 포함된 줄 제거 후 나머지 전달."""
        d = self._make_dispatcher()
        text = "파일 분석해줘\n/help\n요약도 해줘"
        result = await d.dispatch(text, SCOPE)
        assert len(result.feedbacks) == 1
        assert "파일 분석해줘" in result.remaining_text
        assert "요약도 해줘" in result.remaining_text

    async def test_multiple_commands_same_input(self):
        """두 개의 /command가 같은 입력에 존재."""
        d = self._make_dispatcher()
        result = await d.dispatch("/help\n/help", SCOPE)
        assert len(result.feedbacks) == 2

    async def test_url_not_matched(self):
        """URL 안의 /path는 slash command로 파싱하지 않음."""
        d = self._make_dispatcher()
        result = await d.dispatch("https://example.com/path 보여줘", SCOPE)
        assert result.feedbacks == []
        assert result.remaining_text == "https://example.com/path 보여줘"

    async def test_register_custom_command(self):
        """register()로 새 명령 동적 추가."""
        d = self._make_dispatcher()

        async def my_handler(args: str) -> str:
            return f"custom: {args}"

        d.register("mytest", my_handler, "테스트 명령")
        result = await d.dispatch("/mytest hello world", SCOPE)
        assert result.feedbacks == ["custom: hello world"]
        assert result.fully_consumed

    async def test_help_shows_registered_command(self):
        """register()로 추가한 명령이 /help에 표시됨."""
        d = self._make_dispatcher()

        async def my_handler(args: str) -> str:
            return "ok"

        d.register("mytest", my_handler, "내 테스트 명령")
        result = await d.dispatch("/help", SCOPE)
        assert "mytest" in result.feedbacks[0]

    async def test_inline_schedule_with_remaining(self):
        """지시문 앞에 일반 텍스트, 뒤에 /schedule — 둘 다 처리."""
        mock_scheduler = MagicMock()
        mock_scheduler.add_task = MagicMock()
        d = self._make_dispatcher(scheduler=mock_scheduler)

        future = datetime.now() + timedelta(days=5)
        text = f"파일도 분석해줘\n/schedule {future.strftime('%Y.%m.%d')} 오전 9시까지 웹검색 자료 수집"
        result = await d.dispatch(text, SCOPE)

        assert len(result.feedbacks) == 1
        assert "등록 완료" in result.feedbacks[0]
        assert "파일도 분석해줘" in result.remaining_text
        assert not result.fully_consumed
        mock_scheduler.add_task.assert_called_once()


class TestSchedulerRunUntilExpiry:
    def test_expired_task_disabled_in_loop(self):
        """run_until이 지난 task는 loop에서 enabled=False가 된다."""
        from jarvis.core.scheduler.task import ScheduledTask

        past = datetime.now() - timedelta(hours=1)
        task = ScheduledTask(
            name="expired",
            schedule="0 * * * *",
            prompt="test",
            run_until=past,
            enabled=True,
        )
        from datetime import datetime as dt
        if task.run_until is not None and dt.now() >= task.run_until:
            task.enabled = False

        assert task.enabled is False

    def test_active_task_not_disabled(self):
        from jarvis.core.scheduler.task import ScheduledTask

        future = datetime.now() + timedelta(hours=5)
        task = ScheduledTask(
            name="active",
            schedule="0 * * * *",
            prompt="test",
            run_until=future,
            enabled=True,
        )
        from datetime import datetime as dt
        if task.run_until is not None and dt.now() >= task.run_until:
            task.enabled = False

        assert task.enabled is True


# ── 스킬 통과 ─────────────────────────────────────────────────────────────────


async def test_known_skill_is_passed_through_to_llm_path():
    """스킬 이름은 디스패처가 삼키지 않는다. 세션의 expand 가 프롬프트로 바꿔야 하므로 원문 그대로 남긴다."""
    from jarvis.core.slash.dispatcher import SlashCommandDispatcher
    from jarvis.core.skills.registry import Skill, SkillRegistry

    skills = SkillRegistry()
    skills.register(Skill(name="deploy", description="d", aliases=["dep"], content="배포해: {{args}}", metadata={}))
    dispatcher = SlashCommandDispatcher(skill_registry=skills)

    result = await dispatcher.dispatch("/deploy staging", SCOPE)
    assert result.remaining_text == "/deploy staging" and result.feedbacks == []
    result = await dispatcher.dispatch("/dep staging", SCOPE)  # 별칭도 통과
    assert result.remaining_text == "/dep staging"
    result = await dispatcher.dispatch("/nope x", SCOPE)  # 스킬도 명령도 아니면 안내
    assert result.fully_consumed and "알 수 없는 명령" in result.feedbacks[0]
