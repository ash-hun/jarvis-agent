"""스코어카드: 꼭짓점을 돌려 캐시하고, 기준 실측으로 낸 견적이 예산을 넘으면 그 꼭짓점을 건너뛴다."""

import json
from typing import Any
from scripts.experiments import jarvis_scorecard
from scripts.experiments.scorecard_points import vertex_entry

CONFIG: dict[str, Any] = {
    "seed": 0,
    "judge_model": "gpt-4o",
    "reference_polygon": "gpt",
    "budget": {"provider": "anthropic", "cap_usd": 1.0, "estimate_margin": 1.0},
    "prices_per_mtok": {"claude-sonnet-5-5": {"input": 3.0, "output": 15.0}},
    "polygons": [
        {"id": "gpt", "main": "gpt-4o-mini", "thought": "gpt-4o-mini"},
        {"id": "claude", "main": "claude-sonnet-5-5", "thought": "claude-sonnet-5-5"},
    ],
    "vertices": [
        {"id": "cheap", "label": "Cheap", "axis": "A", "role": "main"},
        {"id": "pricey", "label": "Pricey", "axis": "B", "role": "main"},
    ],
}


def install(monkeypatch, tmp_path) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, str]] = []

    def vertex(name: str):  # type: ignore[no-untyped-def]
        async def run(model: str, cfg: dict[str, Any]) -> dict[str, Any]:
            calls.append((name, model))
            return vertex_entry(0.5, 10)

        return run

    monkeypatch.setattr(jarvis_scorecard, "STORE", tmp_path)
    monkeypatch.setattr(jarvis_scorecard, "VERTICES", {"cheap": vertex("cheap"), "pricey": vertex("pricey")})
    return calls


def seed_reference(tmp_path, vertex: str, input_tokens: int) -> None:  # type: ignore[no-untyped-def]
    usage = {"input": input_tokens, "output": 0, "calls": 1 if input_tokens else 0}
    entry = {**vertex_entry(0.5, 10), "usage": {"gpt-4o-mini": usage}}
    (tmp_path / "gpt").mkdir(exist_ok=True)
    (tmp_path / "gpt" / f"{vertex}.json").write_text(json.dumps(entry), encoding="utf-8")


async def test_reference_polygon_runs_every_vertex_and_reruns_read_the_cache(monkeypatch, tmp_path):
    calls = install(monkeypatch, tmp_path)
    gpt = CONFIG["polygons"][0]

    await jarvis_scorecard.run_polygon(gpt, ["cheap", "pricey"], CONFIG)
    await jarvis_scorecard.run_polygon(gpt, ["cheap", "pricey"], CONFIG)

    assert calls == [("cheap", "gpt-4o-mini"), ("pricey", "gpt-4o-mini")]
    assert jarvis_scorecard.collect(CONFIG)["polygons"]["gpt"]["cheap"]["score"] == 50.0


async def test_budget_polygon_skips_vertices_whose_quote_exceeds_the_cap_or_lacks_a_reference(monkeypatch, tmp_path):
    calls = install(monkeypatch, tmp_path)
    seed_reference(tmp_path, "cheap", 100_000)
    seed_reference(tmp_path, "pricey", 1_000_000)
    claude = CONFIG["polygons"][1]

    await jarvis_scorecard.run_polygon(claude, ["cheap", "pricey"], CONFIG)

    assert calls == [("cheap", "claude-sonnet-5-5")]
    (tmp_path / "gpt" / "cheap.json").unlink()
    (tmp_path / "claude" / "cheap.json").unlink()
    await jarvis_scorecard.run_polygon(claude, ["cheap"], CONFIG)
    assert calls == [("cheap", "claude-sonnet-5-5")]


async def test_budget_polygon_uses_fallback_quote_when_the_reference_was_answered_from_cache(monkeypatch, tmp_path):
    calls = install(monkeypatch, tmp_path)
    seed_reference(tmp_path, "cheap", 0)
    seed_reference(tmp_path, "pricey", 0)
    cfg = {**CONFIG, "budget": {**CONFIG["budget"], "fallback_quotes_usd": {"cheap": 0.5}}}

    await jarvis_scorecard.run_polygon(cfg["polygons"][1], ["cheap", "pricey"], cfg)

    assert calls == [("cheap", "claude-sonnet-5-5")]
