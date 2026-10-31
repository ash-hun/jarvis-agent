"""scheduler 가 등록하는 슬래시 디스패처: 텍스트 속 /command 를 실행하고 남은 텍스트와 스킬은 LLM 으로 넘긴다."""

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from jarvis.core.skills.skills_registry import Skill, SkillRegistry
from jarvis.core.slash.dispatcher import SlashCommandDispatcher
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local")


async def test_dispatch_without_slash_passes_text_through():
    result = await SlashCommandDispatcher().dispatch("오늘 날씨 알려줘", SCOPE)

    assert result.feedbacks == []
    assert result.remaining_text == "오늘 날씨 알려줘"
    assert not result.fully_consumed


@pytest.mark.parametrize("text", ["/help", "/?"])
async def test_dispatch_help_and_alias_list_commands(text):
    result = await SlashCommandDispatcher().dispatch(text, SCOPE)

    assert len(result.feedbacks) == 1
    assert "/schedule" in result.feedbacks[0]
    assert result.fully_consumed


async def test_dispatch_unknown_command_reports_it():
    result = await SlashCommandDispatcher().dispatch("/foobar", SCOPE)

    assert len(result.feedbacks) == 1
    assert "알 수 없는 명령" in result.feedbacks[0]


@pytest.mark.parametrize(
    ("text", "remaining"),
    [("이것저것 알려줘 /help", "이것저것 알려줘"), ("앞부분 /help 뒷부분", "앞부분")],
    ids=["at_end", "in_middle_args_absorb_rest_of_line"],
)
async def test_dispatch_inline_command_keeps_text_before_it(text, remaining):
    result = await SlashCommandDispatcher().dispatch(text, SCOPE)

    assert len(result.feedbacks) == 1
    assert "/schedule" in result.feedbacks[0]
    assert result.remaining_text == remaining
    assert not result.fully_consumed


async def test_dispatch_multiline_removes_only_command_line():
    result = await SlashCommandDispatcher().dispatch("파일 분석해줘\n/help\n요약도 해줘", SCOPE)

    assert len(result.feedbacks) == 1
    assert "파일 분석해줘" in result.remaining_text
    assert "요약도 해줘" in result.remaining_text


async def test_dispatch_runs_every_command_in_input():
    result = await SlashCommandDispatcher().dispatch("/help\n/help", SCOPE)

    assert len(result.feedbacks) == 2


async def test_dispatch_ignores_path_inside_url():
    result = await SlashCommandDispatcher().dispatch("https://example.com/path 보여줘", SCOPE)

    assert result.feedbacks == []
    assert result.remaining_text == "https://example.com/path 보여줘"


async def test_registered_command_runs_with_args_and_shows_in_help():
    dispatcher = SlashCommandDispatcher()

    async def my_handler(args: str) -> str:
        return f"custom: {args}"

    dispatcher.register("mytest", my_handler, "테스트 명령")
    result = await dispatcher.dispatch("/mytest hello world", SCOPE)
    help_result = await dispatcher.dispatch("/help", SCOPE)

    assert result.feedbacks == ["custom: hello world"]
    assert result.fully_consumed
    assert "mytest" in help_result.feedbacks[0]


async def test_dispatch_inline_schedule_registers_and_keeps_preceding_text():
    scheduler = MagicMock()
    dispatcher = SlashCommandDispatcher(scheduler=scheduler)
    day = (datetime.now() + timedelta(days=5)).strftime("%Y.%m.%d")

    result = await dispatcher.dispatch(f"파일도 분석해줘\n/schedule {day} 오전 9시까지 웹검색 자료 수집", SCOPE)

    assert len(result.feedbacks) == 1
    assert "등록 완료" in result.feedbacks[0]
    assert "파일도 분석해줘" in result.remaining_text
    assert not result.fully_consumed
    scheduler.add_task.assert_called_once()


async def test_dispatch_passes_skill_names_through_to_llm_path():
    skills = SkillRegistry()
    skills.register(Skill(name="deploy", description="d", aliases=["dep"], content="배포해: {{args}}", metadata={}))
    dispatcher = SlashCommandDispatcher(skill_registry=skills)

    by_name = await dispatcher.dispatch("/deploy staging", SCOPE)
    by_alias = await dispatcher.dispatch("/dep staging", SCOPE)
    unknown = await dispatcher.dispatch("/nope x", SCOPE)

    assert by_name.remaining_text == "/deploy staging" and by_name.feedbacks == []
    assert by_alias.remaining_text == "/dep staging"
    assert unknown.fully_consumed and "알 수 없는 명령" in unknown.feedbacks[0]
