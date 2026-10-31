"""procedures 기능의 노출: 절차 도구의 레시피와 계획 실행, 스킬 변환, 승인된 절차의 멱등 등록과 해제."""

import pytest

from jarvis.core.procedures import (
    STATUS_APPROVED,
    TOOL_PREFIX,
    Procedure,
    ProcedureStore,
    ProcedureTool,
    parse_draft,
    register_approved,
    unregister_procedure,
)
from jarvis.core.policy.pipeline import AuthContext, PolicyResult, SecurityPipeline
from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.core.procedures.tool import INSTRUCTION, register_procedure, to_skill
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.policy.authenticator import NoAuthAuthenticator
from jarvis.core.policy.validator import DefaultInputValidator
from jarvis.core.skills.skills_registry import SkillRegistry
from tests.fixtures.procedures_helpers import PLAN_JSON
from jarvis.core.policy.sandbox import DefaultSandbox
from jarvis.core.policy.policy import AllowAllPolicy
from jarvis.core.procedures.plan import PlanStep
from jarvis.core.session import AgentSession

PLAN_INPUTS = {"test_dir": "tests", "log": "out.log"}


def _procedure() -> Procedure:
    return Procedure(
        name="run-tests",
        description="테스트를 돌리고 요약한다",
        body="1. bash\n입력: {{args}}\n",
        status=STATUS_APPROVED,
        source="s1#0",
        parameters="대상 경로",
    )


def _planned_tool() -> ProcedureTool:
    draft = parse_draft(PLAN_JSON)
    return ProcedureTool(Procedure(name="run-tests", description="d", body="b", inputs=draft.inputs, plan=draft.plan))


class _Session:
    """세션 실행기 흉내. 받은 호출을 남기고 deny 에 든 도구는 승인 거절로 답한다."""

    def __init__(self, deny: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.deny = deny

    async def __call__(self, call_id, name, args):
        self.calls.append((call_id, name, args))
        denied = name in self.deny
        return ToolResultMessage(
            tool_call_id=call_id, tool_name=name, content=[TextContent(text="거절" if denied else f"{name} ok")],
            is_error=denied,
        )


class _Recorder:
    def __init__(self, name: str) -> None:
        self.name, self.description, self.parameters, self.execution_mode = name, name, {}, "parallel"
        self.ran: list[dict] = []

    async def execute(self, tool_call_id, params, signal=None):
        self.ran.append(params)
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name, content=[TextContent(text="ok")])


async def test_procedure_tool_describes_itself_and_returns_rendered_recipe():
    tool = ProcedureTool(_procedure())

    result = await tool.execute("id", {"args": "src/"})

    assert isinstance(tool, JarvisTool)
    assert tool.name == TOOL_PREFIX + "run-tests"
    assert tool.description == "[학습된 절차] 테스트를 돌리고 요약한다 입력: 대상 경로"
    assert not result.is_error
    assert "입력: src/" in result.content[0].text


async def test_procedure_with_plan_runs_each_step_through_the_session_executor():
    tool = _planned_tool()
    session = _Session()

    result = await tool.execute("t1", {"inputs": PLAN_INPUTS}, context=ToolContext(scope=None, call=session))

    assert tool.parameters["properties"]["inputs"]["required"] == ["test_dir", "log"]
    assert not result.is_error
    assert session.calls == [
        ("t1-1", "glob", {"pattern": "tests/**/*.py"}),
        ("t1-2", "bash", {"command": "uv run pytest -q tests"}),
        ("t1-3", "read_file", {"path": "out.log"}),
    ]


async def test_procedure_with_plan_stops_at_refused_step():
    refused = _Session(deny=("bash",))
    context = ToolContext(scope=None, call=refused)

    stopped = await _planned_tool().execute("t2", {"inputs": PLAN_INPUTS}, context=context)

    assert stopped.is_error and [c[1] for c in refused.calls] == ["glob", "bash"]
    assert "2단계에서 멈췄다" in stopped.content[0].text


@pytest.mark.parametrize(
    ("inputs", "has_executor"),
    [({"test_dir": "tests"}, True), (PLAN_INPUTS, False)],
    ids=["missing_input", "no_executor"],
)
async def test_procedure_with_plan_returns_recipe_when_it_cannot_run(inputs, has_executor):
    session = _Session()
    context = ToolContext(scope=None, call=session) if has_executor else None

    result = await _planned_tool().execute("t3", {"inputs": inputs}, context=context)

    assert session.calls == [] and "절차를 순서대로" in result.content[0].text


async def test_procedure_steps_in_a_real_session_still_need_approval(
    faux_model, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
):
    glob, bash = _Recorder("glob"), _Recorder("bash")
    tool_registry.register(glob)
    tool_registry.register(bash)
    plan = (PlanStep("glob", {"pattern": "{{p}}"}), PlanStep("bash", {"command": "echo {{p}}"}))
    tool_registry.register(ProcedureTool(Procedure(name="x", description="d", body="b", inputs=("p",), plan=plan)))
    # 승인 화면이 없으면 bash 는 거절된다. 절차 안의 bash 도 같은 검사를 받아야 한다
    pipeline = SecurityPipeline(
        validator=DefaultInputValidator(), authenticator=NoAuthAuthenticator(), policy=AllowAllPolicy(),
        sandbox=DefaultSandbox(require_approval_for=["bash"]),
    )
    session = AgentSession(
        model=faux_model, session_id="s", security_pipeline=pipeline, plugin_runner=plugin_runner,
        memory=session_memory, tool_registry=tool_registry, skill_registry=skill_registry, session_repo=jsonl_repo,
    )
    executor = session._make_tool_executor(
        AuthContext(user_id="u", roles=frozenset()), PolicyResult(frozenset({"*"}), frozenset({"*"}))
    )

    result = await executor("t1", TOOL_PREFIX + "x", {"inputs": {"p": "*.md"}})

    assert glob.ran == [{"pattern": "*.md"}]
    assert bash.ran == []
    assert result.is_error and "2단계에서 멈췄다" in result.content[0].text


def test_to_skill_carries_instruction_and_source():
    skill = to_skill(_procedure())

    assert skill.name == "run-tests"
    assert skill.content == INSTRUCTION + "1. bash\n입력: {{args}}\n"
    assert skill.metadata == {"procedure": True, "source": "s1#0"}


def test_register_twice_then_unregister_twice_leaves_nothing():
    tools, skills = ToolRegistry(), SkillRegistry()

    register_procedure(_procedure(), tools, skills)
    register_procedure(_procedure(), tools, skills)
    assert [t.name for t in tools.list_all()] == [TOOL_PREFIX + "run-tests"]
    unregister_procedure("run-tests", tools, skills)
    unregister_procedure("run-tests", tools, skills)

    assert tools.get(TOOL_PREFIX + "run-tests") is None
    assert skills.get("run-tests") is None


def test_register_approved_registers_only_approved_and_is_idempotent(tmp_path):
    store = ProcedureStore(str(tmp_path))
    store.save(Procedure(name="a", description="A", body="b", status=STATUS_APPROVED))
    store.save(Procedure(name="b", description="B", body="b"))
    tools, skills = ToolRegistry(), SkillRegistry()

    assert register_approved(store, tools, skills) == ["a"]
    assert register_approved(store, tools, skills) == ["a"]

    assert [t.name for t in tools.list_all()] == [TOOL_PREFIX + "a"]
    assert skills.get("a") is not None and skills.get("b") is None
    assert "b" in skills.expand("/a x")
