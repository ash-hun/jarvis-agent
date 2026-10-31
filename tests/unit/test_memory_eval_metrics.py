"""memory_eval 기능의 판정: 포함, 미포함(누출), 기권 기대를 상위 k 안에서 판정한다."""

from jarvis.memory.eval.eval_schema import EvalCase, Expect, ScopeSpec
from jarvis.memory.eval.metrics import judge


def _case(**expect) -> EvalCase:
    return EvalCase(
        suite="t", case="c", setup=[], scope=ScopeSpec(user_id="u1"), probe="q", expect=Expect(**expect)
    )


def test_judge_contains_not_contains_and_empty():
    assert judge(_case(contains=["a"]), ["xa", "b"]).passed
    assert judge(_case(contains=["a"], top_k=1), ["b", "a"]).missing == ["a"]
    assert judge(_case(not_contains=["secret"]), ["the secret"]).leaked == ["secret"]
    assert judge(_case(empty=True), ["anything"]).broke_abstain
    assert judge(_case(empty=True), []).passed
