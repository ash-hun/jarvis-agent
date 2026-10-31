"""목표 규칙: 자연 키, 답 해석, 새로 알릴 항목 고르기, 진행 기록이 두 번 적어도 한 번만 남는지."""

from jarvis.core.goals.goals_types import (
    MAX_NOTES, Goal, Step, advance, compose, goal_key, new_items, parse_step, with_tool_items, worth_noting,
)

REPLY = (
    "머리: 애쉬, 조건에 맞고 월 부담이 가장 적은 공고예요.\n"
    "항목: [0000061195:59.8000B] 시흥거모 S-1블록, 59.8000B 월 부담 최대 139만원, 11월 17일 마감\n"
    "항목: [2015122300020958:20B] 화성 동탄 행복주택, 20B 월 부담 최대 7만원, 11월 12일 마감\n"
    "기록: 1순위 둘 확인\n"
    "완료: 아니오"
)


def goal(**kw) -> Goal:  # type: ignore[no-untyped-def]
    return Goal(id=goal_key("karen", "공고 알려줘"), agent="karen", text="공고 알려줘", **kw)


def test_same_goal_text_gives_the_same_key_whatever_the_spacing():
    assert goal_key("karen", "조건에 맞는  공고만 알려줘") == goal_key("karen", " 조건에 맞는 공고만 알려줘 ")
    assert goal_key("karen", "공고 알려줘") != goal_key("main", "공고 알려줘")


def test_parse_step_reads_head_keyed_items_note_and_done():
    step = parse_step(REPLY)
    assert step.parsed and not step.done and step.keyless == 0
    assert step.head == "애쉬, 조건에 맞고 월 부담이 가장 적은 공고예요."
    assert [k for k, _ in step.items] == ["0000061195:59.8000B", "2015122300020958:20B"]
    assert step.note == "1순위 둘 확인"


def test_items_without_a_key_and_blank_markers_are_dropped():
    step = parse_step("머리: 없음\n항목: 새 공고는 없어요\n항목: 없음\n기록: 변화 없음\n완료: 아니오")
    assert step.parsed and step.head == "" and step.items == () and step.keyless == 1


def test_free_text_reply_is_not_parsed():
    assert parse_step("애쉬, 공고가 두 건이에요.") == Step()


def test_only_unreported_items_are_composed_with_the_head():
    step = parse_step(REPLY)
    g = goal(reported=["0000061195:59.8000B"])
    fresh = new_items(g, step)
    assert [k for k, _ in fresh] == ["2015122300020958:20B"]
    assert compose(step, fresh) == "애쉬, 조건에 맞고 월 부담이 가장 적은 공고예요.\n" + step.items[1][1]
    assert compose(step, []) == ""


def test_duplicate_keys_in_one_reply_count_once():
    step = Step(items=(("a", "x"), ("a", "y")), parsed=True)
    assert new_items(goal(), step) == [("a", "x")]


def test_advance_twice_with_the_same_keys_keeps_them_once():
    step = parse_step(REPLY)
    keys = [k for k, _ in step.items]
    g = advance(advance(goal(), step, keys, 1), step, keys, 2)
    assert g.reported == keys and g.runs == 2


def test_notes_keep_only_the_latest():
    g = goal()
    for i in range(MAX_NOTES + 5):
        g = advance(g, Step(note=f"n{i}", parsed=True), [], i)
    assert len(g.notes) == MAX_NOTES and g.notes[-1] == f"n{MAX_NOTES + 4}"


def test_done_step_closes_the_goal():
    assert advance(goal(), Step(done=True, parsed=True), [], 1).status == "done"


def test_reply_without_field_labels_is_still_read():
    """모델이 머리표 없이 첫 줄 머리와 '[키] 줄' 만 썼다(실측)."""
    step = parse_step(
        "애쉬, 조건에 맞고 월 부담이 가장 적은 공고예요.\n"
        "[0000061195:59.8000B] 시흥거모, 월 부담 최대 139만원\n"
        "[2015122300020958:20B] 화성 동탄, 월 부담 최대 7만원\n\n"
        "기록: 추천함\n완료: 아니오"
    )
    assert step.parsed and step.head == "애쉬, 조건에 맞고 월 부담이 가장 적은 공고예요."
    assert [k for k, _ in step.items] == ["0000061195:59.8000B", "2015122300020958:20B"] and step.note == "추천함"


def test_head_repeating_the_only_item_is_dropped():
    line = "추천 공고를 찾으려면 보유 현금과 월 여유자금이 필요해요."
    step = Step(head=f"애쉬, {line}", items=(("ask-money", line),), parsed=True)
    assert compose(step, list(step.items)) == line


def test_only_turns_that_used_a_tool_and_did_more_than_ask_leave_a_note():
    """도구 없이 답한 차례와 묻기만 한 차례의 기록은 남기지 않는다. 그 기록이 사용자가 답한 뒤에도 다시 묻게 했다."""
    asked = Step(items=(("ask-money", "현금을 알려 주세요"),), note="현금 모름", parsed=True)
    picked = Step(items=(("ask-money", "현금"), ("2026:55A", "서울 행복주택")), note="1순위 알림", parsed=True)
    quiet = Step(note="새 공고 없음", parsed=True)
    assert not worth_noting(asked, used_tool=True) and not worth_noting(picked, used_tool=False)
    assert worth_noting(picked, used_tool=True) and worth_noting(quiet, used_tool=True)


def test_items_the_tool_wrote_are_taken_from_its_result_not_from_the_model():
    """도구가 지은 '항목: [키] 줄' 은 모델이 옮기지 않거나 키를 빼도 그대로 알린다. 같은 키면 도구 줄이 이긴다."""
    result = "보유 현금을 모른다\n항목: [ask-money] 현금을 알려 주세요\n추천 1순위(임대) 항목: [n1] 행복주택, 링크"
    model = Step(items=(("n1", "행복주택(줄인 링크)"), ("n2", "다른 것")), parsed=True)
    merged = with_tool_items(model, [result])
    assert merged.items == (("ask-money", "현금을 알려 주세요"), ("n1", "행복주택, 링크"), ("n2", "다른 것"))
    assert with_tool_items(model, ["항목 없는 결과"]) is model
    # 묻기만 할 때는 추천 머리를 붙이지 않는다
    asking = Step(head="애쉬, 조건에 맞는 공고예요.", parsed=True)
    assert compose(asking, [("ask-money", "현금을 알려 주세요")]) == "현금을 알려 주세요"

