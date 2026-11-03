"""[app] 화면에서 고칠 수 있는 설정 허용 목록과 settings.yaml 읽기, 쓰기, 비밀값을 가린 조회."""

import os
import re
import yaml
import tempfile
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

from jarvis.jarvis_config import JarvisSettings
from jarvis.common.logger import get_logger

logger = get_logger(__name__)
# 이름에 이 낱말이 들어간 값은 화면에 내보내지 않는다. 키 자체가 비밀인 security.api_keys 도 여기 걸린다
SECRET_NAME = re.compile(r"((^|_)(api_keys?|key|token|secret|password|dsn)$|webhook)", re.IGNORECASE)
MASK = "***"


class VoicePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stt_provider: Literal["browser", "whisper"] | None = None
    stt_fallback: Literal["", "whisper"] | None = None
    tts_provider: Literal["browser", "supertonic"] | None = None
    whisper_model_size: Literal["tiny", "base", "small", "medium"] | None = None
    stt_lang: str | None = Field(default=None, pattern=r"^[a-z]{2}-[A-Z]{2}$")
    tts_lang: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    wake_threshold: float | None = Field(default=None, ge=0.05, le=0.99)


class ProactivePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    daemon_enabled: bool | None = None
    daemon_trigger: Literal["interval", "idle", "both"] | None = None
    daemon_interval_sec: int | None = Field(default=None, ge=30, le=3600)
    daemon_idle_sec: int | None = Field(default=None, ge=30, le=3600)
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    cooldown_sec: int | None = Field(default=None, ge=0, le=86400)


class ThoughtPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    router_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class FocusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None


class SettingsPatch(BaseModel):
    """PUT /api/settings 본문. 비운 섹션과 필드는 건드리지 않는다."""

    model_config = ConfigDict(extra="forbid")

    voice: VoicePatch | None = None
    proactive: ProactivePatch | None = None
    thought: ThoughtPatch | None = None
    focus: FocusPatch | None = None


def mask_secrets(value: Any, name: str = "") -> Any:
    """이름이 비밀값처럼 보이는 항목을 MASK 로 바꾼 사본. 빈 값은 비어 있다는 사실만 보이게 그대로 둔다."""
    if name and SECRET_NAME.search(name):
        return MASK if value else value
    if isinstance(value, dict):
        return {k: mask_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_secrets(v) for v in value]
    return value


def editable_values(settings: JarvisSettings) -> dict[str, dict[str, Any]]:
    """허용 목록에 든 필드의 지금 적용값. 화면 폼의 초기값이다."""
    result: dict[str, dict[str, Any]] = {}
    for section, field in SettingsPatch.model_fields.items():
        patch_cls = field.annotation.__args__[0]  # type: ignore[union-attr]
        current = getattr(settings, section)
        result[section] = {name: getattr(current, name) for name in patch_cls.model_fields}
    return result


def editable_fields() -> dict[str, dict[str, dict[str, Any]]]:
    """화면 폼을 그릴 필드 정의(type, enum, minimum, maximum, title). SettingsPatch 에서 유도해 허용 목록이 정본이다."""
    schema = SettingsPatch.model_json_schema()
    defs = schema.get("$defs", {})
    fields: dict[str, dict[str, dict[str, Any]]] = {}
    for section, prop in schema["properties"].items():
        ref = next(o["$ref"] for o in prop["anyOf"] if "$ref" in o)
        section_fields: dict[str, dict[str, Any]] = {}
        for name, field in defs[ref.rsplit("/", 1)[-1]]["properties"].items():
            spec = next(o for o in field["anyOf"] if o.get("type") != "null")
            keep = {k: spec[k] for k in ("type", "enum", "minimum", "maximum", "pattern") if k in spec}
            section_fields[name] = {"title": field.get("title", name), **keep}
        fields[section] = section_fields
    return fields


def merge_patch(stored: dict[str, Any], patch: SettingsPatch) -> dict[str, Any]:
    """yaml 에 저장된 값 위에 patch 를 얹은 새 dict. 같은 patch 를 두 번 얹어도 결과가 같다."""
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in stored.items()}
    for section, values in patch.model_dump(exclude_none=True).items():
        merged.setdefault(section, {}).update(values)
    return merged


class SettingsOverlay:
    """settings.yaml 하나를 맡는다. 고친 값은 백엔드를 다시 띄워야 반영된다."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        loaded = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}

    def apply(self, patch: SettingsPatch) -> bool:
        """patch 를 저장한다. 파일 내용이 바뀌었으면 True. 바뀐 게 없으면 파일을 건드리지 않는다."""
        stored = self.read()
        merged = merge_patch(stored, patch)
        if merged == stored:
            return False
        # 합친 결과가 설정 모델로 읽히는지 먼저 본다. 깨진 파일을 남기면 백엔드가 뜨지 못한다
        JarvisSettings.model_validate(merged)
        self._write_atomic(yaml.safe_dump(merged, allow_unicode=True, sort_keys=True))
        sections = sorted(patch.model_dump(exclude_none=True))
        logger.info("[Settings] settings.yaml 갱신", path=str(self._path), sections=sections)
        return True

    def _write_atomic(self, text: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".settings-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
