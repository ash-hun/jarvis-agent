"""[core] 메인 LLM 이 작업에 맞는 패턴과 참여 에이전트를 골라 오케스트레이션을 시작하는 도구."""

import asyncio
from typing import Any

from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool, ToolContext
from .service import PATTERNS, OrchestrationService


class OrchestrateTool(JarvisTool):
    name = "orchestrate"
    execution_mode = "sequential"

    def __init__(self, service: OrchestrationService) -> None:
        self._service = service
        agents = "; ".join(f"{d.name}: {d.description}" for d in service.definitions) or "(없음)"
        patterns = "; ".join(f"{k}: {v}" for k, v in PATTERNS.items())
        self.description = (
            "Run several sub-agents together under a coordination pattern. Use for tasks that need more than one "
            f"specialist or more than one pass. Patterns: {patterns}. Available agents: {agents}. "
            "Join patterns with commas to pipeline them (e.g. 'hierarchical,blackboard')."
        )
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Coordination pattern, or comma-joined patterns for a pipeline.",
                    "enum": list(PATTERNS),
                },
                "task": {"type": "string", "description": "What the agents should accomplish."},
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Agent names to involve. Omit to use all defined agents.",
                },
                "promote": {
                    "type": "boolean",
                    "description": "Blackboard only: save each agent's result as shared long-term facts.",
                },
            },
            "required": ["pattern", "task"],
        }

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        try:
            result = await self._service.run(
                str(params["pattern"]),
                str(params["task"]),
                agents=params.get("agents") or None,
                promote=bool(params.get("promote", False)),
                parent_scope=getattr(context, "scope", None),
            )
        except ValueError as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id, tool_name=self.name, content=[TextContent(text=str(exc))], is_error=True
            )
        text = result.content if result.success else f"[orchestration error] {result.error}"
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(text=text or "(empty)")],
            is_error=not result.success,
        )
