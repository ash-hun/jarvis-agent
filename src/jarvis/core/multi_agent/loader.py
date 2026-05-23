"""YAML 기반 AgentDefinition 로더.

~/.jarvis/agents/*.yaml 파일을 읽어 AgentDefinition 목록을 반환한다.
scheduler/loader.py 패턴과 동일.

YAML 포맷 (단일):
    name: researcher
    description: "웹 검색과 문서 분석을 담당하는 에이전트"
    capabilities:
      - web_search
      - read_file
    system_prompt: |
      당신은 리서처입니다...
    tools:
      - web_search
      - read_file
    model_override: null   # null이면 메인 모델 상속

YAML 포맷 (리스트):
    - name: planner
      description: ...
    - name: executor
      description: ...
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .factory import AgentDefinition

_VALID_FIELDS = frozenset({
    "name", "description", "capabilities",
    "system_prompt", "tools", "model_override",
})


def load_agent_definitions(agents_dir: str) -> list[AgentDefinition]:
    """지정 디렉토리의 모든 *.yaml 파일에서 AgentDefinition 목록을 로딩한다."""
    try:
        import yaml
    except ImportError:
        print("[AgentLoader] PyYAML not installed — skipping agent definitions")
        return []

    root = Path(agents_dir).expanduser()
    if not root.exists():
        return []

    definitions: list[AgentDefinition] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                defn = _parse_definition(data)
                if defn is not None:
                    definitions.append(defn)
            elif isinstance(data, list):
                for item in data:
                    defn = _parse_definition(item)
                    if defn is not None:
                        definitions.append(defn)
        except Exception as exc:
            print(f"[AgentLoader] Failed to load '{path}': {exc}")

    return definitions


def _parse_definition(data: Any) -> AgentDefinition | None:
    """dict → AgentDefinition 변환. 필수 필드 누락 시 None 반환."""
    if not isinstance(data, dict):
        return None
    if not data.get("name") or not data.get("description"):
        return None
    filtered = {k: v for k, v in data.items() if k in _VALID_FIELDS}
    try:
        return AgentDefinition(**filtered)
    except Exception as exc:
        print(f"[AgentLoader] Invalid agent definition ({data.get('name')}): {exc}")
        return None
