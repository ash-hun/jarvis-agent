"""focus 기능의 순수 함수: 명령 해석, 진행률, 예상 시간, 단계 병합, 분석 렌더링, 상태 직렬화."""

import pytest

from jarvis.core.focus.focus_types import (
    FocusCommand,
    FocusState,
    FocusStep,
    apply_plan,
    eta_sec,
    extract_json,
    latest_section,
    parse_command,
    progress,
    render_analysis,
)


def _state(steps: tuple[FocusStep, ...]) -> FocusState:
    return FocusState(task_id="t", session_id="s", task="작업", started_at=100.0, steps=steps)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/focus 랜딩 페이지 카피 다듬기", FocusCommand("start", "랜딩 페이지 카피 다듬기")),
        ("/focus", FocusCommand("status")),
        ("/focus stop", FocusCommand("stop")),
        ("/FOCUS 종료", FocusCommand("stop")),
        ("  /focus  off ", FocusCommand("stop")),
        ("focus 모드 알려줘", None),
        ("/focused 작업", None),
        ("오늘 /focus 할까", None),
    ],
)
def test_parse_command_reads_only_leading_focus_command(text: str, expected: FocusCommand | None) -> None:
    assert parse_command(text) == expected


@pytest.mark.parametrize(
    ("steps", "expected"),
    [((), 0.0), ((FocusStep("a", 110.0), FocusStep("b"), FocusStep("c"), FocusStep("d")), 0.25)],
)
def test_progress_is_done_step_ratio(steps: tuple[FocusStep, ...], expected: float) -> None:
    assert progress(steps) == expected


@pytest.mark.parametrize(
    ("steps", "now", "expected"),
    [
        ((FocusStep("a"), FocusStep("b")), 200.0, None),
        # 90초에 1단계 완료, 남은 2단계 = 180초. 시간이 더 흐르면 예상도 늘어난다
        ((FocusStep("a", 160.0), FocusStep("b"), FocusStep("c")), 190.0, 180.0),
        ((FocusStep("a", 160.0), FocusStep("b"), FocusStep("c")), 400.0, 600.0),
        ((FocusStep("a", 150.0),), 500.0, 0.0),
    ],
)
def test_eta_sec_is_elapsed_per_done_step_times_remaining(
    steps: tuple[FocusStep, ...], now: float, expected: float | None
) -> None:
    assert eta_sec(_state(steps), now=now) == expected


@pytest.mark.parametrize(
    ("steps", "plan", "expected"),
    [
        (
            (FocusStep("조사", 120.0), FocusStep("초안")),
            [
                {"title": "조사", "done": True},
                {"title": "초안", "done": True},
                {"title": "검토", "done": False},
                {"title": "검토", "done": True},
                {"title": "  "},
            ],
            (FocusStep("조사", 120.0), FocusStep("초안", 300.0), FocusStep("검토")),
        ),
        ((FocusStep("조사"),), [], (FocusStep("조사"),)),
    ],
)
def test_apply_plan_keeps_done_time_and_stamps_new_completions(
    steps: tuple[FocusStep, ...], plan: list[dict[str, object]], expected: tuple[FocusStep, ...]
) -> None:
    assert apply_plan(steps, plan, now=300.0) == expected


def test_apply_plan_twice_is_same() -> None:
    plan = [{"title": "조사", "done": True}, {"title": "초안", "done": False}]
    once = apply_plan((), plan, now=300.0)

    again = apply_plan(once, plan, now=999.0)

    assert again == once


@pytest.mark.parametrize(
    ("text", "expected"),
    [('```json\n{"steps": []}\n```', {"steps": []}), ("no json", None), ("[1, 2]", None)],
)
def test_extract_json_reads_object_through_fences(text: str, expected: dict[str, object] | None) -> None:
    assert extract_json(text) == expected


def test_render_analysis_lists_five_items() -> None:
    md = render_analysis({"purpose": ["전환율 개선"], "next": "A/B 테스트 요청", "needs": []})

    assert "- **근본 목적**\n  - 전환율 개선" in md
    assert "- **예상 다음 지시**\n  - A/B 테스트 요청" in md
    assert "- **필요한 것**\n  - 없음" in md
    assert md.count("**") == 10
    assert not md.startswith("*지시")


def test_render_analysis_names_the_instruction() -> None:
    md = render_analysis({"purpose": ["가"], "instruction": "첫 3일을 조정해줘", "at": "16:26"})

    assert md.splitlines()[0] == "*지시: 첫 3일을 조정해줘 · 16:26*"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("## 조사: A\n\n가\n\n## 조사: B\n\n나\n\n", "## 조사: B\n\n나\n\n"), ("조사 없음", "조사 없음")],
)
def test_latest_section_keeps_last_research(text: str, expected: str) -> None:
    assert latest_section(text, "## 조사: ") == expected


def test_state_round_trips_json() -> None:
    state = FocusState("t", "s", "작업", 1.0, (FocusStep("a", 2.0), FocusStep("b")), ("지시",))

    assert FocusState.from_json(state.to_json()) == state
