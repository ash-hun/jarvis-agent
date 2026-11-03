"""[scripts] τ²-bench 공식 보상(끝난 DB 와 정답 DB 의 일치, 필요한 정보의 전달)을 순수 함수로 계산한다."""

# 출처: sierra-research/tau2-bench v2.0.0 src/tau2/evaluator/evaluator.py, evaluator_env.py,
# evaluator_communicate.py 의 SUBSTRING 채점 (MIT License, Copyright (c) 2025 Sierra Research).
# 공식과 다른 점 두 가지는 아래 required_outputs 와 communicated 에 적었다

from typing import Any

# 공식 evaluate_simulation 은 이 두 종료만 채점하고 나머지(max_steps, too_many_errors, 오류)는 0 점이다
SCORED_TERMINATIONS = frozenset({"user_stop", "agent_stop"})


def required_outputs(criteria: dict[str, Any]) -> list[str]:
    """에이전트가 사용자에게 말해야 하는 값들.

    COMMUNICATE 가 보상 기준이면 communicate_info 그대로다(airline). retail 은 v2.0.0 에서 NL_ASSERTION
    (LLM 판정)으로 바뀌었는데, 판정문이 있는 과제의 communicate_info 가 같은 값을 짝으로 갖고 있어
    ("the camera costs $481.50" 와 "481.5") 판정 호출 없이 그 값으로 대신 본다.
    """
    # ponytail: retail NL_ASSERTION 을 짝 값의 substring 으로 본다, 판정 비용을 감수할 때 공식 판정 프롬프트로 바꾼다
    basis = set(criteria.get("reward_basis") or [])
    info = list(criteria.get("communicate_info") or [])
    if "COMMUNICATE" in basis:
        return info
    if "NL_ASSERTION" in basis and criteria.get("nl_assertions"):
        return info
    return []


def communicated(required: list[str], agent_texts: list[str]) -> list[bool]:
    """공식 SUBSTRING 채점: 에이전트 글 하나에 값이 소문자로, 쉼표를 지운 글 안에 들어 있는가.

    공식 기본값은 의미 판정 LLM(semantic)이지만 재현과 비용 때문에 공식이 함께 두는 substring 방식을 쓴다.
    """
    lowered = [text.lower().replace(",", "") for text in agent_texts if text]
    return [any(value.lower() in text for text in lowered) for value in required]


def score_episode(
    *,
    termination: str,
    predicted_changes: dict[str, dict[str, str]],
    gold_changes: dict[str, dict[str, str]],
    criteria: dict[str, Any],
    agent_texts: list[str],
) -> dict[str, Any]:
    """과제 하나의 보상(0 또는 1). DB 는 같은 초기 DB 위에서 바뀐 레코드끼리 비교한다(전체 해시 비교와 같다)."""
    if termination not in SCORED_TERMINATIONS:
        return {"reward": 0.0, "db_match": None, "outputs": [], "note": f"terminated: {termination}"}
    basis = set(criteria.get("reward_basis") or [])
    has_db_target = criteria.get("actions") is not None or criteria.get("env_assertions") is not None
    db_match = predicted_changes == gold_changes if has_db_target else True
    required = required_outputs(criteria)
    outputs = communicated(required, agent_texts)
    reward = 1.0
    if "DB" in basis:
        reward *= float(db_match)
    if required:
        reward *= float(all(outputs))
    return {"reward": reward, "db_match": db_match, "outputs": dict(zip(required, outputs, strict=True)),
            "note": ""}


def pass_hat_1(rewards: list[float]) -> float:
    """시도 한 번의 pass^1 은 과제별 보상의 평균이다."""
    return sum(rewards) / len(rewards) if rewards else 0.0
