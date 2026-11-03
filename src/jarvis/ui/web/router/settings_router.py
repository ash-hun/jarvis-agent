"""[ui] 설정 조회와 허용 목록 편집 REST, 백엔드가 살아 있는지 보는 health. Settings 화면과 데스크톱 셸이 쓴다."""

from typing import Any
from pydantic import ValidationError
from fastapi.responses import JSONResponse
from fastapi import APIRouter, HTTPException

from jarvis.app.settings_overlay import SettingsPatch, SettingsOverlay, mask_secrets, editable_fields, editable_values
from jarvis.common.app_version import app_version
from jarvis.ui.web.web_state import WebState

SETTINGS_EXAMPLE = {
    "path": "/root/.jarvis/settings.yaml",
    "fields": {"voice": {"wake_threshold": {
        "title": "Wake Threshold", "type": "number", "minimum": 0.05, "maximum": 0.99}}},
    "editable": {"voice": {"stt_provider": "browser", "wake_threshold": 0.5}},
    "pending": {"voice": {"wake_threshold": 0.7}},
    "effective": {"llm": {"provider": "anthropic", "api_key": "***"}},
}


def pending_changes(stored: dict[str, Any], editable: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """yaml 에는 있지만 지금 프로세스에 아직 반영되지 않은 값. 비어 있지 않으면 백엔드를 다시 띄워야 한다."""
    pending: dict[str, dict[str, Any]] = {}
    for section, values in editable.items():
        saved = stored.get(section)
        if not isinstance(saved, dict):
            continue
        diff = {k: v for k, v in saved.items() if k in values and values[k] != v}
        if diff:
            pending[section] = diff
    return pending


def build_settings_router(state: WebState, overlay: SettingsOverlay) -> APIRouter:
    router = APIRouter(tags=["settings"])

    def _snapshot() -> dict[str, Any]:
        settings = state.settings
        editable = editable_values(settings)
        return {
            "path": str(overlay.path),
            "fields": editable_fields(),
            "editable": editable,
            "pending": pending_changes(overlay.read(), editable),
            "effective": mask_secrets(settings.model_dump(mode="json")),
        }

    @router.get(
        "/api/health",
        summary="백엔드 상태",
        description="떠 있으면 200 과 패키지 버전. 데스크톱 셸이 백엔드를 띄울지 정하고, HUD 헤더가 버전을 보인다.",
        responses={200: {"content": {"application/json": {"example": {"ok": True, "version": "0.2.0"}}}}},
    )
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "version": app_version()})

    @router.get(
        "/api/settings",
        summary="설정 조회",
        description=(
            "effective 는 지금 프로세스의 전체 적용값(비밀값은 ***), fields 는 고칠 수 있는 항목의 형식과 범위,"
            " editable 은 그 항목의 적용값,"
            " pending 은 settings.yaml 에 저장됐지만 아직 반영되지 않은 값이다."
        ),
        responses={200: {"content": {"application/json": {"example": SETTINGS_EXAMPLE}}}},
    )
    async def get_settings() -> JSONResponse:
        return JSONResponse(_snapshot())

    @router.put(
        "/api/settings",
        summary="설정 편집",
        description=(
            "허용 목록(voice, proactive, thought, focus 의 일부) 안의 값만 받아 settings.yaml 에 저장한다."
            " 모르는 필드와 범위 밖 값은 422. 백엔드를 다시 띄워야 반영된다. 같은 본문을 다시 보내면 changed=false."
        ),
        responses={200: {"content": {"application/json": {"example": {"changed": True, **SETTINGS_EXAMPLE}}}}},
    )
    async def put_settings(patch: SettingsPatch) -> JSONResponse:
        try:
            changed = overlay.apply(patch)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
        return JSONResponse({"changed": changed, **_snapshot()})

    return router
