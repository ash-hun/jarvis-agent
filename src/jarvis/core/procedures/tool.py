"""[core] 승인된 절차를 LLM 도구와 슬래시 스킬로 노출한다(도구는 절차 본문을 돌려준다)."""

import asyncio
from typing import Any

from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.core.procedures.procedures_store import Procedure, ProcedureStore
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.skills.skills_registry import Skill, SkillRegistry
from jarvis.core.procedures.plan import fill

TOOL_PREFIX = "procedure_"
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "args": {"type": "string", "description": "절차에 넘길 입력(대상 파일, 경로, 조건 등). 없으면 빈 문자열"},
    },
    "required": [],
}
# 단계마다 결과에 싣는 글자 수. 긴 파일 내용이 다음 턴 맥락을 채우지 않게 자른다
STEP_RESULT_CHARS = 2000
INSTRUCTION = (
    "아래 절차를 순서대로 도구를 호출해 수행하고, 끝나면 결과를 요약하라. "
    "결과가 뻔해 보여도 단계를 건너뛰지 말고 각 단계의 도구 호출을 실제로 실행하라.\n\n"
)


class ProcedureTool(JarvisTool):
    """실행 계획이 있고 입력이 다 오면 단계를 차례로 실행한다. 아니면 본문(레시피)을 돌려 모델이 따라 하게 한다."""

    execution_mode = "sequential"

    def __init__(self, procedure: Procedure) -> None:
        self._procedure = procedure
        self.name = TOOL_PREFIX + procedure.name
        self.description = f"[학습된 절차] {procedure.description}"
        if procedure.parameters:
            self.description += f" 입력: {procedure.parameters}"
        self.parameters = _parameters(procedure)

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        raw = params.get("inputs")
        values: dict[str, Any] = raw if isinstance(raw, dict) else {}
        plan = self._procedure.plan
        if plan and context is not None and context.call is not None and set(self._procedure.inputs) <= set(values):
            return await self._run(tool_call_id, values, context)
        args = str(params.get("args", "") or "")
        return self._result(tool_call_id, INSTRUCTION + self._procedure.render(args))

    async def _run(self, tool_call_id: str, values: dict[str, Any], context: ToolContext) -> ToolResultMessage:
        """단계마다 세션 실행기를 거친다. 실패하거나 승인이 거절되면 거기서 멈추고 남은 단계는 하지 않는다."""
        assert context.call is not None
        lines = [f"절차 {self._procedure.name} 를 순서대로 실행했다. 결과를 요약해 답한다."]
        for i, step in enumerate(self._procedure.plan, 1):
            result = await context.call(f"{tool_call_id}-{i}", step.tool, fill(step.args, values))
            text = "".join(c.text for c in result.content if isinstance(c, TextContent))[:STEP_RESULT_CHARS]
            lines.append(f"\n[{i}단계 {step.tool}{' 실패' if result.is_error else ''}]\n{text}")
            if result.is_error:
                lines.append(f"\n{i}단계에서 멈췄다. 남은 단계는 실행하지 않았다.")
                return self._result(tool_call_id, "\n".join(lines), is_error=True)
        return self._result(tool_call_id, "\n".join(lines))

    def _result(self, tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
        return ToolResultMessage(
            tool_call_id=tool_call_id, tool_name=self.name, content=[TextContent(text=text)], is_error=is_error
        )


def _parameters(procedure: Procedure) -> dict[str, Any]:
    """계획이 있으면 입력을 이름별로 받는다. 레시피용 args 는 계획 없는 절차와 같은 모양으로 둔다."""
    if not procedure.plan:
        return TOOL_PARAMETERS
    inputs = {name: {"type": "string"} for name in procedure.inputs}
    return {
        "type": "object",
        "properties": {
            **TOOL_PARAMETERS["properties"],
            "inputs": {"type": "object", "properties": inputs, "required": list(procedure.inputs)},
        },
        "required": ["inputs"] if procedure.inputs else [],
    }


def to_skill(procedure: Procedure) -> Skill:
    return Skill(
        name=procedure.name,
        description=procedure.description,
        aliases=[],
        content=INSTRUCTION + procedure.body,
        metadata={"procedure": True, "source": procedure.source},
    )


def register_procedure(procedure: Procedure, tools: ToolRegistry, skills: SkillRegistry) -> None:
    """도구 레지스트리는 first-wins 라 두 번 등록해도 하나다. 스킬은 같은 이름을 덮어쓴다(내용 동일)."""
    tools.register(ProcedureTool(procedure))
    skills.register(to_skill(procedure))


def unregister_procedure(name: str, tools: ToolRegistry, skills: SkillRegistry) -> None:
    tools.unregister(TOOL_PREFIX + name)
    skills.unregister(name)


def register_approved(store: ProcedureStore, tools: ToolRegistry, skills: SkillRegistry) -> list[str]:
    """저장소의 승인된 절차 전부를 등록한다. 기동 때와 승인 직후에 부른다."""
    names: list[str] = []
    for procedure in store.list():
        if procedure.approved:
            register_procedure(procedure, tools, skills)
            names.append(procedure.name)
    return names
