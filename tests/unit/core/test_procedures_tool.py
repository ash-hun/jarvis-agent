"""절차 노출과 증류: 스킬 변환, 등록 해제, LLM 증류기의 성공과 실패."""

from jarvis.core.procedures import (
    STATUS_APPROVED,
    TOOL_PREFIX,
    Procedure,
    ProcedureTool,
    TaskSpan,
    ToolStep,
    llm_distiller,
    unregister_procedure,
)
from jarvis.model_layer.model_types import AssistantMessage, ModelConfig, TextContent
from jarvis.core.procedures.tool import INSTRUCTION, register_procedure, to_skill
from jarvis.core.tools.tools_registry import JarvisTool, ToolRegistry
from jarvis.core.skills.skills_registry import SkillRegistry

MODEL = ModelConfig(provider="faux", model="faux-model")
SPAN = TaskSpan(
    start=0,
    request="테스트 돌리고 요약해줘",
    steps=(ToolStep(name="bash", args={"command": "pytest"}),),
    outcome="3개 통과",
)


def _procedure() -> Procedure:
    return Procedure(
        name="run-tests",
        description="테스트를 돌리고 요약한다",
        body="1. bash\n입력: {{args}}\n",
        status=STATUS_APPROVED,
        source="s1#0",
        parameters="대상 경로",
    )


def test_procedure_tool_is_jarvis_tool_with_description():
    tool = ProcedureTool(_procedure())
    assert isinstance(tool, JarvisTool)
    assert tool.name == TOOL_PREFIX + "run-tests"
    assert tool.description == "[학습된 절차] 테스트를 돌리고 요약한다 입력: 대상 경로"


def test_to_skill_carries_instruction_and_source():
    skill = to_skill(_procedure())
    assert skill.name == "run-tests"
    assert skill.content == INSTRUCTION + "1. bash\n입력: {{args}}\n"
    assert skill.metadata == {"procedure": True, "source": "s1#0"}


def test_register_twice_then_unregister_leaves_nothing():
    tools, skills = ToolRegistry(), SkillRegistry()
    register_procedure(_procedure(), tools, skills)
    register_procedure(_procedure(), tools, skills)
    assert [t.name for t in tools.list_all()] == [TOOL_PREFIX + "run-tests"]
    unregister_procedure("run-tests", tools, skills)
    unregister_procedure("run-tests", tools, skills)  # 두 번 불러도 같다
    assert tools.get(TOOL_PREFIX + "run-tests") is None
    assert skills.get("run-tests") is None


async def test_llm_distiller_parses_reply(monkeypatch):
    prompts: list[str] = []

    async def fake_stream(model, ctx, options):
        prompts.append(ctx.messages[0].content)
        reply = '{"name": "Run Tests", "description": "테스트 요약", "steps": ["bash 로 실행"]}'
        return AssistantMessage(content=[TextContent(text=reply)])

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)
    draft = await llm_distiller(MODEL)(SPAN)
    assert draft is not None
    assert (draft.name, draft.description, draft.steps) == ("run-tests", "테스트 요약", ("bash 로 실행",))
    assert "테스트 돌리고 요약해줘" in prompts[0]


async def test_llm_distiller_returns_none_on_model_error(monkeypatch):
    async def fake_stream(model, ctx, options):
        return AssistantMessage(content=[TextContent(text="{}")], error_message="rate limited")

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)
    assert await llm_distiller(MODEL)(SPAN) is None
