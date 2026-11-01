"""procedures 기능의 reflector 입출력: JSON 스키마 검증, 넘침 근거와 거부 이유를 담은 프롬프트."""

from jarvis.core.procedures.reflect import Attempt, FailureCase, parse_reflection, render_prompt


def test_parse_reflection_reads_json_inside_text():
    raw = 'ok {"scope": "procedure", "action": "revise_procedure", "content": "1. a", "extra": 1} done'

    parsed = parse_reflection(raw)

    assert parsed is not None
    assert (parsed.scope, parsed.action, parsed.content) == ("procedure", "revise_procedure", "1. a")


def test_parse_reflection_rejects_unknown_scope_or_broken_json():
    assert parse_reflection('{"scope": "routing", "action": "no_change"}') is None
    assert parse_reflection("{not json") is None
    assert parse_reflection("no braces") is None


def test_render_prompt_includes_overflow_and_refusal():
    case = FailureCase("main", "bash", (Attempt("빌드 고쳐", "실패", overflow=True),), procedure="1. make")

    text = render_prompt(case, "범위가 맞지 않는다")

    assert "넘침" in text and "범위가 맞지 않는다" in text and "1. make" in text and "빌드 고쳐" in text
    assert "거부된 이유" not in render_prompt(case)


def test_parse_reflection_accepts_step_list_and_comma_keywords():
    raw = '{"scope": "procedure", "action": "revise_procedure", "content": ["1. a", "2. b"], "keywords": "x, y"}'

    parsed = parse_reflection(raw)

    assert parsed is not None and parsed.content == "1. a\n2. b" and parsed.keywords == ["x", " y"]
