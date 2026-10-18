"""[core] 셸 명령을 실행해 stdout/stderr 를 돌려주는 bash 내장 도구."""

import asyncio
from typing import Any

from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool

TOOL_NAME = "bash"
TOOL_DESCRIPTION = "Execute a bash command and return stdout/stderr. Use with caution."
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "The bash command to execute"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
    },
    "required": ["command"],
}


class BashTool(JarvisTool):
    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "sequential"

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        command = params["command"]
        timeout = params.get("timeout", 30)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    content=[TextContent(text=f"Command timed out after {timeout}s")],
                    is_error=True,
                )

            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")
            is_error = proc.returncode != 0
            text = output + (f"\n[stderr]\n{error}" if error else "")

            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=text or "(no output)")],
                is_error=is_error,
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )
