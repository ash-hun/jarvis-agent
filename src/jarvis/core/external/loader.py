"""[core] 외부 소스 선언 YAML 을 읽어 ExternalSourceSpec 목록으로 만든다."""

import yaml
from typing import Any
from pathlib import Path
from pydantic import BaseModel, Field

from jarvis.common.logger import get_logger

logger = get_logger(__name__)


class ExternalSourceSpec(BaseModel):
    """YAML 한 항목 = 외부 소스 1개 선언."""

    name: str
    server: str  # config의 mcp_servers 이름 참조
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    interval_sec: float = 300.0
    enabled: bool = True


def load_source_specs(sources_dir: str) -> list[ExternalSourceSpec]:
    """`~/.jarvis/external_sources/*.yaml`에서 소스 선언을 로딩한다.

    디렉토리가 없으면 빈 목록. 폴러가 아예 기동하지 않는 무해한 no-op.
    파일/항목 단위로 격리해 하나의 오류가 나머지 로딩을 막지 않는다.
    """
    root = Path(sources_dir).expanduser()
    if not root.exists():
        return []

    specs: list[ExternalSourceSpec] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as exc:
            logger.info(f"[ExternalSourceLoader] Failed to read '{path}': {exc}")
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                specs.append(ExternalSourceSpec.model_validate(item))
            except Exception as exc:
                logger.info(f"[ExternalSourceLoader] Skipping invalid source in '{path}': {exc}")
    return specs
