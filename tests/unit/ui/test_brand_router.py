"""브랜드 주입: brand.js 는 window.BRAND 와 CSS 변수를, manifest 는 이름과 색만 에이전트 것으로 바꾼다."""

import json

from jarvis.ui.web.router.brand_router import STATIC_DIR, render_brand_js, render_manifest
from jarvis.config import BrandConfig


def _brand() -> BrandConfig:
    return BrandConfig.model_validate(
        {"name": "F.R.I.D.A.Y.", "quote": "준비 완료", "palette": {"background": "#010203"}}
    )


def test_render_brand_js_embeds_brand_json_and_sets_css_vars():
    brand = _brand()
    js = render_brand_js(brand)
    first_line = js.splitlines()[0]
    assert first_line.startswith("window.BRAND = ") and first_line.endswith(";")
    assert json.loads(first_line[len("window.BRAND = "):-1]) == brand.model_dump()
    assert "준비 완료" in js  # ensure_ascii=False
    for var in ("--primary", "--accent", "--bg-0", "--nebula-"):
        assert var in js


def test_render_brand_js_is_deterministic():
    assert render_brand_js(_brand()) == render_brand_js(_brand())


def test_render_manifest_overrides_name_and_colors_only():
    base = json.loads((STATIC_DIR / "manifest.json").read_text("utf-8"))
    manifest = render_manifest(_brand())
    assert manifest["name"] == "F.R.I.D.A.Y. · HUD"
    assert manifest["short_name"] == "F.R.I.D.A.Y."
    assert manifest["background_color"] == manifest["theme_color"] == "#010203"
    changed = {"name", "short_name", "background_color", "theme_color"}
    untouched = {k: v for k, v in manifest.items() if k not in changed}
    assert untouched == {k: v for k, v in base.items() if k not in changed}
