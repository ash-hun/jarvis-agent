"""[ui] 브랜드 라우트: 에이전트의 워드마크, 명언, 색을 brand.js 와 manifest.json 으로 화면에 주입한다."""

import json
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from jarvis.jarvis_config import BrandConfig
from jarvis.ui.web.web_state import WebState

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BRAND_JS_EXAMPLE = 'window.BRAND = {"name": "J.A.R.V.I.S.", ...};\n(function (p) { ... })(window.BRAND.palette);\n'


def render_brand_js(brand: BrandConfig) -> str:
    """<head> 에서 동기 로드되는 스크립트. 첫 페인트 전에 CSS 변수와 window.BRAND 를 채운다."""
    # 개성 문장은 모델에게 주는 지시라 화면에 싣지 않는다
    payload = json.dumps(brand.model_dump(exclude={"persona"}), ensure_ascii=False)
    return (
        f"window.BRAND = {payload};\n"
        "(function (p) {\n"
        "  var s = document.documentElement.style;\n"
        "  s.setProperty('--primary', p.primary);\n"
        "  s.setProperty('--accent', p.accent);\n"
        "  s.setProperty('--bg-0', p.background);\n"
        "  p.nebula.forEach(function (c, i) { s.setProperty('--nebula-' + i, c); });\n"
        "})(window.BRAND.palette);\n"
    )


def render_manifest(brand: BrandConfig) -> dict[str, object]:
    """정적 manifest.json 을 바탕으로 이름과 색만 에이전트 것으로 바꾼다."""
    manifest: dict[str, object] = json.loads((STATIC_DIR / "manifest.json").read_text("utf-8"))
    manifest["name"] = f"{brand.name} · HUD"
    manifest["short_name"] = brand.name
    manifest["background_color"] = brand.palette.background
    manifest["theme_color"] = brand.palette.background
    return manifest


def build_brand_router(state: WebState) -> APIRouter:
    # 정적 셸은 에이전트와 무관하게 두고, 정체성은 이 두 라우트로만 주입한다
    router = APIRouter(tags=["brand"])
    brand = state.assembly.profile.brand

    @router.get(
        "/brand.js",
        summary="브랜드 스크립트",
        description="window.BRAND 와 색 CSS 변수를 채우는 JS. index.html 의 <head> 가 동기로 읽는다.",
        response_class=Response,
        responses={200: {"content": {"application/javascript": {"example": BRAND_JS_EXAMPLE}}}},
    )
    async def brand_js() -> Response:
        return Response(
            render_brand_js(brand), media_type="application/javascript", headers={"Cache-Control": "no-cache"}
        )

    @router.get(
        "/manifest.json",
        summary="PWA manifest",
        description="정적 manifest.json 에서 이름과 배경, 테마 색만 에이전트 브랜드로 바꾼다.",
        responses={200: {"content": {"application/json": {"example": {"name": "J.A.R.V.I.S. · HUD"}}}}},
    )
    async def manifest() -> JSONResponse:
        return JSONResponse(render_manifest(brand))

    return router
