"""Open-loop 스토어(Tier 2 C1) 단위 테스트."""
from __future__ import annotations

from datetime import datetime

import pytest

from jarvis.agent_layer.openloop import (
    InMemoryOpenLoopStore,
    OpenLoop,
    OpenLoopStore,
    close_expired,
    normalize_description,
    parse_loop_note,
)
from jarvis.agent_layer.openloop.types import (
    cancelled_ids,
    expired_ids,
    grounded,
    matching_ids,
    merge_loop,
    refers_to,
    same_loop,
)


def test_store_satisfies_protocol():
    assert isinstance(InMemoryOpenLoopStore(), OpenLoopStore)


@pytest.mark.asyncio
async def test_add_and_get():
    store = InMemoryOpenLoopStore()
    loop = OpenLoop(description="배포 결과 공유", origin_session="s1")
    lid = await store.add(loop)
    got = await store.get(lid)
    assert got is not None and got.description == "배포 결과 공유"
    assert got.status == "open"


@pytest.mark.asyncio
async def test_add_unique_dedups_open_same_session():
    store = InMemoryOpenLoopStore()
    first = await store.add_unique(OpenLoop(description="배포  결과 공유", origin_session="s1"))
    # 공백/대소문자만 다른 중복 → 추가 안 함.
    dup = await store.add_unique(OpenLoop(description="배포 결과 공유", origin_session="s1"))
    assert first is not None
    assert dup is None
    assert len(await store.all()) == 1


@pytest.mark.asyncio
async def test_add_unique_allows_other_session_and_other_desc():
    store = InMemoryOpenLoopStore()
    await store.add_unique(OpenLoop(description="A 작업", origin_session="s1"))
    other_session = await store.add_unique(OpenLoop(description="A 작업", origin_session="s2"))
    other_desc = await store.add_unique(OpenLoop(description="B 작업", origin_session="s1"))
    assert other_session is not None
    assert other_desc is not None
    assert len(await store.all()) == 3


@pytest.mark.asyncio
async def test_add_unique_ignores_blank():
    store = InMemoryOpenLoopStore()
    assert await store.add_unique(OpenLoop(description="   ", origin_session="s1")) is None


@pytest.mark.asyncio
async def test_list_open_filters_status_and_session():
    store = InMemoryOpenLoopStore()
    a = await store.add(OpenLoop(description="열림1", origin_session="s1"))
    await store.add(OpenLoop(description="열림2", origin_session="s2"))
    done = await store.add(OpenLoop(description="완료됨", origin_session="s1"))
    await store.update_status(done, "done")

    s1_open = await store.list_open(session_id="s1")
    assert [x.id for x in s1_open] == [a]  # done·다른세션 제외

    all_open = await store.list_open()
    assert len(all_open) == 2  # 세션 무관 열린 항목


@pytest.mark.asyncio
async def test_update_status_validation():
    store = InMemoryOpenLoopStore()
    lid = await store.add(OpenLoop(description="x"))
    assert await store.update_status(lid, "done") is True
    assert (await store.get(lid)).status == "done"
    assert await store.update_status(lid, "bogus") is False
    assert await store.update_status("nonexistent", "done") is False


def test_normalize_description():
    assert normalize_description("  배포   결과 ") == "배포 결과"
    assert normalize_description("ABC") == "abc"


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("배포 결과 공유", "배포  결과 공유", True),
        ("로그 확인해줘", "내일 배포 전에 로그 확인해줘", True),  # 포함
        ("로그", "배포 로그 확인", False),  # 6자 미만 조각은 우연
        ("배포 결과 공유", "회의록 정리", False),
        ("", "배포", False),
    ],
)
def test_same_loop_containment(a, b, same):
    assert same_loop(a, b) is same


async def test_add_unique_treats_contained_description_as_same():
    store = InMemoryOpenLoopStore()
    assert await store.add_unique(OpenLoop(description="내일 배포 전에 로그 확인해줘", origin_session="s1"))
    assert await store.add_unique(OpenLoop(description="로그 확인해줘", origin_session="s1")) is None
    assert await store.add_unique(OpenLoop(description="로그 확인해줘", origin_session="s2"))


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        # 실제로 쌓였던 바꿔 말한 중복
        (
            "내일 오전 10시 팀 배포 결과 공유 회의 준비 및 진행",
            "내일 오전 10시 팀 배포 결과 공유 회의 준비 및 핵심 메시지 구조화 완료",
            True,
        ),
        (
            "내일 오전 10시 회의의 구체적인 아젠다 및 발표 범위",
            "내일 오전 10시 팀 배포 결과 공유 회의의 구체적인 아젠다 및 발표 범위 확정",
            True,
        ),
        ("회의 참석자들의 최종 리스트 확정", "참석자들의 최종 리스트 확정", True),
        # 끝말(확정)만 같은 다른 약속
        ("참석자 목록 확정", "원하는 알림 주기(시간) 확정", False),
        ("핵심 메시지 3가지 구조화 작업 완료 여부 확인", "내일 오전 10시 팀 배포 결과 공유 회의 준비 및 진행", False),
    ],
)
def test_same_loop_catches_paraphrase(a, b, same):
    assert same_loop(a, b) is same


def test_parse_loop_note_splits_due():
    desc, due = parse_loop_note("배포 결과 공유 회의 준비 @2026-10-12 10:00")
    assert desc == "배포 결과 공유 회의 준비"
    assert due == int(datetime(2026, 10, 12, 10, 0).timestamp() * 1000)
    assert parse_loop_note("회의 준비 @2026-10-12T9:05")[1] == int(datetime(2026, 10, 12, 9, 5).timestamp() * 1000)


@pytest.mark.parametrize("note", ["리뷰 답변", "  리뷰 답변  "])
def test_parse_loop_note_without_due(note):
    assert parse_loop_note(note) == ("리뷰 답변", None)


def test_parse_loop_note_bad_date_keeps_description():
    assert parse_loop_note("리뷰 답변 @2026-13-40 10:00") == ("리뷰 답변", None)


def _loop(desc, *, due=None, session="s1", created=0, status="open"):
    return OpenLoop(description=desc, due_ms=due, origin_session=session, created_at=created, status=status)


def test_merge_loop_new_when_no_match():
    new = _loop("리뷰 답변")
    assert merge_loop([_loop("배포 결과 공유")], new) is new


def test_merge_loop_fills_due_once():
    existing = _loop("배포 결과 공유 회의 준비")
    updated = merge_loop([existing], _loop("배포 결과 공유 회의 준비 및 진행", due=1000))
    assert updated is not None and updated.id == existing.id and updated.due_ms == 1000
    assert updated.description == existing.description
    # 갱신된 상태에서 같은 걸 또 넣으면 바뀔 게 없다
    assert merge_loop([updated], _loop("배포 결과 공유 회의 준비 및 진행", due=1000)) is None


def test_merge_loop_ignores_closed_and_other_session():
    new = _loop("배포 결과 공유")
    assert merge_loop([_loop("배포 결과 공유", status="done"), _loop("배포 결과 공유", session="s2")], new) is new


async def test_add_unique_updates_paraphrase_instead_of_adding():
    store = InMemoryOpenLoopStore()
    first = await store.add_unique(_loop("내일 오전 10시 팀 배포 결과 공유 회의 준비 및 진행"))
    again = await store.add_unique(
        _loop("내일 오전 10시 팀 배포 결과 공유 회의 준비 및 핵심 메시지 구조화 완료", due=5000)
    )
    assert again == first
    loops = await store.list_open()
    assert len(loops) == 1 and loops[0].due_ms == 5000


def test_expired_ids_rules():
    loops = [
        _loop("기한 지남", due=1_000),
        _loop("여유 안", due=9_000),
        _loop("오래된 기한 없음", created=0),
        _loop("최근 기한 없음", created=9_500),
        _loop("닫힌 것", due=1_000, status="done"),
    ]
    ids = {x.id: x.description for x in loops}
    got = [ids[i] for i in expired_ids(loops, now_ms=10_000, grace_ms=2_000, max_age_ms=5_000)]
    assert got == ["기한 지남", "오래된 기한 없음"]
    assert [ids[i] for i in expired_ids(loops, now_ms=10_000, grace_ms=2_000, max_age_ms=0)] == ["기한 지남"]


async def test_close_expired_twice_is_same():
    store = InMemoryOpenLoopStore()
    loop_id = await store.add(_loop("기한 지남", due=1_000))
    assert await close_expired(store, now_ms=10_000, grace_ms=0, max_age_ms=0) == [loop_id]
    assert await close_expired(store, now_ms=10_000, grace_ms=0, max_age_ms=0) == []
    assert (await store.get(loop_id)).status == "expired"


@pytest.mark.parametrize(
    ("note", "desc", "hit"),
    [
        (
            "분기 보고서 초안을 팀장님께 보내는 일정은 취소되었습니다.",
            "내일 오후 3시까지 분기 보고서 초안을 팀장님께 보내야 해.",
            True,
        ),
        ("핵심 메시지 구조화는 안 해도 됨", "핵심 메시지 3가지 구조화 작업 완료 여부 확인", True),
        ("참석자 목록 확정 취소", "원하는 알림 주기(시간) 확정", False),
        ("배포 결과 공유 완료", "리뷰 답변 보내기", False),
    ],
)
def test_refers_to(note, desc, hit):
    assert refers_to(note, desc) is hit


@pytest.mark.parametrize(
    ("note", "picked"), [("1", [0]), ("[2]", [1]), ("2번", [1]), ("[1] 아무 문구", [0]), ("9", [])]
)
def test_matching_ids_by_number(note, picked):
    shown = [_loop("분기 보고서 초안 제출"), _loop("리뷰 답변")]
    assert matching_ids(shown, [note]) == [shown[i].id for i in picked]


def test_matching_ids_by_text_and_skips_closed():
    shown = [_loop("분기 보고서 초안 제출"), _loop("리뷰 답변", status="done")]
    assert matching_ids(shown, ["분기 보고서 초안 제출은 취소", "리뷰 답변"]) == [shown[0].id]


def test_grounded():
    assert grounded("분기 보고서 초안을 팀장님께 제출", "내일 오후 3시까지 분기 보고서 초안을 팀장님께 보내야 해")
    assert not grounded("핵심 메시지 3가지 구조화 작업", "분기 보고서 초안 보내는 건 취소됐어")
    assert not grounded("오늘 할 일 한 줄 요약", "분기 보고서 초안 보내는 건 취소됐어")


def test_cancelled_ids_needs_cue_and_target():
    shown = [_loop("분기 보고서 초안 보냄"), _loop("리뷰 답변")]
    assert cancelled_ids(shown, "분기 보고서 초안 보내는 건 취소됐어. 안 챙겨도 돼") == [shown[0].id]
    assert cancelled_ids(shown, "분기 보고서 초안 보내는 거 어떻게 돼가?") == []
    assert cancelled_ids(shown, "그건 취소됐어") == []
    assert cancelled_ids(shown, "보고서 분량은 그만큼이면 돼") == []
