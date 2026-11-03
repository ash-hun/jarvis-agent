"""[tests] τ²-bench 공식 보상 계산, 옮긴 도구의 DB 변경, 표본 고르기와 단계 세기를 검증한다."""

import copy
from typing import Any
from scripts.experiments.tau2_bench import count_steps, gold_changes, pick_tasks, user_instructions
from scripts.experiments.tau2_score import communicated, pass_hat_1, required_outputs, score_episode
from scripts.experiments.tau2_tools import AirlineTools, OverlayDB, RetailTools, calculate_expression

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolCall, UserMessage


def _retail_base() -> dict[str, dict[str, Any]]:
    address = {"address1": "1 Main", "address2": "", "city": "X", "country": "USA", "state": "CA", "zip": "1"}
    order = {
        "order_id": "#W1", "user_id": "ann_1", "status": "pending", "items": [], "fulfillments": [],
        "address": dict(address),
        "payment_history": [{"transaction_type": "payment", "amount": 40.0, "payment_method_id": "gift_card_1"}],
        "cancel_reason": None,
    }
    user = {"user_id": "ann_1", "name": {"first_name": "Ann", "last_name": "Lee"}, "email": "a@x.com",
            "address": dict(address),
            "payment_methods": {"gift_card_1": {"source": "gift_card", "id": "gift_card_1", "balance": 10.0}},
            "orders": ["#W1"]}
    return {"products": {}, "users": {"ann_1": user}, "orders": {"#W1": order}}


def _airline_base() -> dict[str, dict[str, Any]]:
    user = {"user_id": "bo_2", "payment_methods": {}, "reservations": []}
    return {"flights": {}, "users": {"bo_2": user}, "reservations": {}}


def test_cancel_pending_order_changes_order_and_refunds_gift_card() -> None:
    base = _retail_base()
    frozen = copy.deepcopy(base)
    db = OverlayDB(base)
    text, failed = RetailTools(db).call("cancel_pending_order", {"order_id": "#W1", "reason": "no longer needed"})
    assert not failed and '"status": "cancelled"' in text
    assert db.get("users", "ann_1")["payment_methods"]["gift_card_1"]["balance"] == 50.0
    assert set(db.changes()) == {"orders", "users"}
    assert base == frozen


def test_cancel_rejects_bad_reason_without_change() -> None:
    db = OverlayDB(_retail_base())
    text, failed = RetailTools(db).call("cancel_pending_order", {"order_id": "#W1", "reason": "too slow"})
    assert failed and text == "Error: Invalid reason"
    assert db.changes() == {}


def test_unknown_argument_is_an_error_result() -> None:
    text, failed = RetailTools(OverlayDB(_retail_base())).call("get_order_details", {"id": "#W1"})
    assert failed and text.startswith("Error:")


def test_send_certificate_adds_float_certificate() -> None:
    db = OverlayDB(_airline_base())
    text, failed = AirlineTools(db).call("send_certificate", {"user_id": "bo_2", "amount": 100})
    assert not failed and "certificate_3221322" in text
    assert db.get("users", "bo_2")["payment_methods"]["certificate_3221322"]["amount"] == 100.0


def test_gold_changes_skip_failed_actions() -> None:
    actions = [{"name": "get_order_details", "arguments": {"order_id": "#W9"}},
               {"name": "cancel_pending_order", "arguments": {"order_id": "#W1", "reason": "ordered by mistake"}}]
    changes = gold_changes("retail", _retail_base(), actions)
    assert '"cancel_reason": "ordered by mistake"' in changes["orders"]["#W1"]


def test_calculate_expression_rounds() -> None:
    assert calculate_expression("(10 + 2) / 3 * 1.005") == "4.02"


def test_calculate_expression_rejects_names() -> None:
    try:
        calculate_expression("__import__('os')")
    except ValueError as exc:
        assert "Invalid characters" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_required_outputs_by_basis() -> None:
    airline = {"reward_basis": ["DB", "COMMUNICATE"], "communicate_info": ["10"]}
    retail_judged = {"reward_basis": ["DB", "NL_ASSERTION"], "nl_assertions": ["tell 46.66"],
                     "communicate_info": ["46.66"]}
    retail_plain = {"reward_basis": ["DB", "NL_ASSERTION"], "nl_assertions": None, "communicate_info": ["5"]}
    assert required_outputs(airline) == ["10"]
    assert required_outputs(retail_judged) == ["46.66"]
    assert required_outputs(retail_plain) == []


def test_communicated_drops_commas_and_case() -> None:
    assert communicated(["8276.23", "Polyester"], ["Total is $8,276.23 for POLYESTER"]) == [True, True]


def test_communicated_missing_value() -> None:
    assert communicated(["44.08"], ["about 44 dollars", ""]) == [False]


def _criteria() -> dict[str, Any]:
    return {"reward_basis": ["DB", "COMMUNICATE"], "communicate_info": ["22.55"], "actions": []}


def test_score_episode_full_reward() -> None:
    same = {"orders": {"#W1": "{}"}}
    out = score_episode(termination="user_stop", predicted_changes=same, gold_changes=dict(same),
                        criteria=_criteria(), agent_texts=["You pay $22.55."])
    assert out["reward"] == 1.0 and out["db_match"] is True


def test_score_episode_db_mismatch_and_premature_end() -> None:
    mismatch = score_episode(termination="user_stop", predicted_changes={}, gold_changes={"orders": {"#W1": "{}"}},
                             criteria=_criteria(), agent_texts=["22.55"])
    cut = score_episode(termination="max_steps", predicted_changes={}, gold_changes={}, criteria=_criteria(),
                        agent_texts=["22.55"])
    assert mismatch["reward"] == 0.0 and cut["reward"] == 0.0 and cut["db_match"] is None


def test_pass_hat_1() -> None:
    assert pass_hat_1([1.0, 0.0, 1.0, 1.0]) == 0.75
    assert pass_hat_1([]) == 0.0


def test_pick_tasks_is_fixed_and_interleaved() -> None:
    ids = {"retail": [str(i) for i in range(40)], "airline": [str(i) for i in range(20)]}
    first = pick_tasks(ids, 20, seed=0)
    assert first == pick_tasks({"airline": ids["airline"][::-1], "retail": ids["retail"]}, 20, seed=0)
    assert len(first) == 40 and [d for d, _ in first[:4]] == ["airline", "retail", "airline", "retail"]
    assert pick_tasks(ids, 20, seed=0, limit=5) == first[:5]


def test_pick_tasks_small_pool() -> None:
    assert pick_tasks({"airline": ["3"]}, 20, seed=1) == [("airline", "3")]


def test_count_steps_counts_tool_batches() -> None:
    call = AssistantMessage(content=[ToolCall(id="c", name="calculate", arguments={})])
    reply = AssistantMessage(content=[TextContent(text="done")])
    assert count_steps([UserMessage(content="hi"), call, reply]) == 4


def test_user_instructions_matches_official_layout() -> None:
    scenario = {"persona": None, "instructions": {"domain": "retail", "reason_for_call": "Return a lamp.",
                                                  "known_info": None, "unknown_info": None,
                                                  "task_instructions": "Be brief."}}
    assert user_instructions(scenario) == (
        "Instructions:\n\tDomain: retail\n\tReason for call:\n\t\tReturn a lamp.\n\tTask instructions:\n\t\tBe brief.")
