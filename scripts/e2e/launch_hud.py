"""Web HUD 를 스크립트 프로바이더(실 LLM 없음)와 격리된 임시 디렉토리로 띄운다. e2e 검증용.

uv run python scripts/e2e/launch_hud.py &          # 7799 포트
uv run --with playwright python scripts/e2e/hud_flow.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.gettempdir())
WORK = Path(tempfile.mkdtemp(prefix="jarvis-e2e-"))
(ROOT / "jarvis-e2e-workdir").write_text(str(WORK))

os.environ.update(
    {
        "JARVIS_LLM__PROVIDER": "scripted",
        "JARVIS_LLM__MODEL": "scripted-1",
        "JARVIS_MEMORY__BACKEND": "in_memory",
        "JARVIS_SESSION__PERSISTENCE_BACKEND": "jsonl",
        "JARVIS_SESSION__SESSIONS_DIR": str(WORK / "sessions"),
        "JARVIS_PROCEDURES__DIR": str(WORK / "procedures"),
        "JARVIS_SECURITY__APPROVALS_PATH": str(WORK / "approvals.yaml"),
        "JARVIS_SECURITY__API_KEYS": "{}",
        "JARVIS_THOUGHT__ENABLED": "false",
        "JARVIS_PROACTIVE__ENABLED": "false",
        "JARVIS_PROACTIVE__DAEMON_ENABLED": "false",
        "JARVIS_SCHEDULER__ENABLED": "false",
        "JARVIS_AGENTS__ENABLED": "false",
        "JARVIS_EXTERNAL__ENABLED": "false",
        "JARVIS_PLUGIN__TOOLS_DIR": str(WORK / "tools"),
        "JARVIS_PLUGIN__SKILLS_DIR": str(WORK / "skills"),
        "JARVIS_PLUGIN__PLUGINS_DIR": str(WORK / "plugins"),
        "JARVIS_OPENLOOP__BACKEND": "in_memory",
        "JARVIS_USER_MODEL__BACKEND": "in_memory",
    }
)

from jarvis.model_layer.registry import get_default_registry  # noqa: E402
from jarvis.model_layer.types import StopEvent, TextDeltaEvent, ToolCallDeltaEvent, Usage  # noqa: E402

SCRIPTS = {
    "run-echo": ([("bash", {"command": "echo hello"})], "done: hello"),
    "multi": (
        [
            ("glob", {"pattern": "*.md"}),
            ("read_file", {"path": "README.md", "limit": 3}),
            ("bash", {"command": "echo multi"}),
        ],
        "세 단계 작업 완료.",
    ),
}
DISTILL = json.dumps(
    {
        "name": "scan-and-echo",
        "description": "마크다운을 훑고 README 를 읽은 뒤 셸로 확인한다",
        "parameters": "확인할 디렉토리",
        "steps": ["glob 으로 *.md 나열", "read_file 로 README 앞부분 확인", "bash 로 echo 실행"],
    },
    ensure_ascii=False,
)
SILENT_FRAME = json.dumps({"decision": "silent", "confidence": 0.1})


def _text(m):
    c = getattr(m, "content", "")
    if isinstance(c, str):
        return c
    return " ".join(getattr(b, "text", "") for b in c if getattr(b, "text", ""))


class ScriptedProvider:
    provider_name = "scripted"

    def supports_thinking(self):
        return False

    def supports_images(self):
        return False

    async def stream(self, model, context, options=None):
        msgs = context.messages
        if context.tools is None:
            prompt = _text(msgs[-1]) if msgs else ""
            if "[도구 호출 순서]" in prompt:
                yield TextDeltaEvent(delta=DISTILL)
            elif "JSON" in prompt and "decision" in prompt:
                yield TextDeltaEvent(delta=SILENT_FRAME)
            else:
                yield TextDeltaEvent(delta="요약: 테스트 세션")
            yield StopEvent(reason="stop", usage=Usage(input=5, output=5))
            return

        # 메모리 블록([핵심 사실] 등)도 user 역할이라 "[" 로 시작하지 않는 마지막 사용자 메시지를 찾는다
        users = [i for i, m in enumerate(msgs) if m.role == "user" and isinstance(m.content, str)]
        idx = max((i for i in users if not msgs[i].content.startswith("[")), default=-1)
        text = msgs[idx].content.strip() if idx >= 0 else ""
        steps, final = SCRIPTS.get(text, ([], f"echo: {text}"))
        done = sum(1 for m in msgs[idx + 1 :] if m.role == "tool_result")
        if done < len(steps):
            name, args = steps[done]
            yield ToolCallDeltaEvent(id=f"call_{done}", name=name, arguments_delta=json.dumps(args))
            yield StopEvent(reason="tool_use", usage=Usage(input=10, output=5))
        else:
            yield TextDeltaEvent(delta=final)
            yield StopEvent(reason="stop", usage=Usage(input=10, output=5))


get_default_registry().register(ScriptedProvider())

from jarvis.ui.tui.startup import main  # noqa: E402

sys.argv = ["jarvis", "--web", "--port", "7799"]
main()
