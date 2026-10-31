"""[core] 정규식으로 파일 내용을 검색해 'path:line: text' 로 돌려주는 grep 내장 도구."""

import re
import asyncio
from typing import Any
from pathlib import Path
from collections.abc import Iterator

from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.tools.tools_registry import JarvisTool

TOOL_NAME = "grep"
TOOL_DESCRIPTION = (
    "Search file contents by regular expression. Returns matching lines as "
    "'path:line_number: text'. Use this to find where code/text lives without "
    "running shell commands. Binary and undecodable files are skipped."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Regular expression to search for (Python re syntax)",
        },
        "path": {
            "type": "string",
            "description": "File or directory to search (default: current directory)",
        },
        "glob": {
            "type": "string",
            "description": "Only search files matching this glob, e.g. '*.py' (default: all files)",
        },
        "case_insensitive": {
            "type": "boolean",
            "description": "Case-insensitive matching (default: false)",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of matching lines to return (default: 100)",
        },
    },
    "required": ["pattern"],
}

# 노이즈/대용량 디렉토리는 탐색에서 제외
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


class GrepTool(JarvisTool):
    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        pattern = params["pattern"]
        root = Path(params.get("path", ".")).expanduser()
        file_glob = params.get("glob")
        max_results = int(params.get("max_results", 100))
        flags = re.IGNORECASE if params.get("case_insensitive") else 0

        if not root.exists():
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Path not found: {root}")],
                is_error=True,
            )

        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Invalid regex: {exc}")],
                is_error=True,
            )

        matches = await asyncio.to_thread(_grep, root, regex, file_glob, max_results)

        if not matches:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"No matches for: {pattern}")],
            )

        truncated = "\n(results truncated)" if len(matches) >= max_results else ""
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(text="\n".join(matches) + truncated)],
        )


def _iter_files(root: Path, file_glob: str | None) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    candidates = root.rglob(file_glob) if file_glob else root.rglob("*")
    for p in candidates:
        if p.is_file() and not (_SKIP_DIRS & set(p.parts)):
            yield p


def _grep(root: Path, regex: re.Pattern[str], file_glob: str | None, max_results: int) -> list[str]:
    results: list[str] = []
    for path in _iter_files(root, file_glob):
        try:
            with path.open(encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if regex.search(line):
                        results.append(f"{path}:{lineno}: {line.rstrip()}")
                        if len(results) >= max_results:
                            return results
        except (UnicodeDecodeError, OSError):
            continue  # 바이너리/읽기 불가 파일은 건너뜀
    return results
