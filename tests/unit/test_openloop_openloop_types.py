"""openloop: 같은 약속 판정, 기한과 근거 해석, 병합, 만료, 닫기 대상 고르기 순수 규칙을 검증한다."""

import pytest
from datetime import datetime

from jarvis.agent_layer.openloop.openloop_types import (
    OpenLoop,
    grounded,
    merge_loop,
    refers_to,
    same_loop,
    expired_ids,
    matching_ids,
    cancelled_ids,
    split_evidence,
    parse_loop_note,
    normalize_description,
)


def _loop(desc, *, due=None, session="s1", created=0, status="open"):
    return OpenLoop(description=desc, due_ms=due, origin_session=session, created_at=created, status=status)


def _ms(*args: int) -> int:
    return int(datetime(*args).timestamp() * 1000)


@pytest.mark.parametrize(("text", "normalized"), [("  배포   결과 ", "배포 결과"), ("ABC", "abc")])
def test_normalize_description_collapses_spaces_and_lowercases(text, normalized):
    assert normalize_description(text) == normalized


@pytest.mark.parametrize(
    ("a", "b", "similarity", "same"),
    [
        ("배포 결과 공유", "배포  결과 공유", None, True),
        ("로그 확인해줘", "내일 배포 전에 로그 확인해줘", None, True),
        ("로그", "배포 로그 확인", None, False),  # 6자 미만 조각의 포함은 우연
        ("배포 결과 공유", "회의록 정리", None, False),
        ("", "배포", None, False),
        # 실제로 쌓였던 바꿔 말한 중복
        (
            "내일 오전 10시 팀 배포 결과 공유 회의 준비 및 진행",
            "내일 오전 10시 팀 배포 결과 공유 회의 준비 및 핵심 메시지 구조화 완료",
            None,
            True,
        ),
        (
            "내일 오전 10시 회의의 구체적인 아젠다 및 발표 범위",
            "내일 오전 10시 팀 배포 결과 공유 회의의 구체적인 아젠다 및 발표 범위 확정",
            None,
            True,
        ),
        ("회의 참석자들의 최종 리스트 확정", "참석자들의 최종 리스트 확정", None, True),
        ("참석자 목록 확정", "원하는 알림 주기(시간) 확정", None, False),
        (
            "핵심 메시지 3가지 구조화 작업 완료 여부 확인",
            "내일 오전 10시 팀 배포 결과 공유 회의 준비 및 진행",
            None,
            False,
        ),
        # 글자로는 0.21 이라 못 잡는 실제 중복을 임베딩 유사도로 잡는다
        ("참석자 목록 확정", "회의 참석자들의 최종 리스트 확정", None, False),
        ("참석자 목록 확정", "회의 참석자들의 최종 리스트 확정", 0.89, True),
        ("참석자 목록 확정", "회의 참석자들의 최종 리스트 확정", 0.80, False),
        ("배포 결과 공유", "배포  결과 공유", 0.1, True),
    ],
)
def test_same_loop_matches_text_containment_paraphrase_or_similarity(a, b, similarity, same):
    assert same_loop(a, b, similarity=similarity) is same


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("배포 결과 공유 회의 준비 @2026-10-12 10:00", ("배포 결과 공유 회의 준비", _ms(2026, 10, 12, 10, 0))),
        ("회의 준비 @2026-10-12T9:05", ("회의 준비", _ms(2026, 10, 12, 9, 5))),
        ("리뷰 답변", ("리뷰 답변", None)),
        ("  리뷰 답변  ", ("리뷰 답변", None)),
        ("리뷰 답변 @2026-13-40 10:00", ("리뷰 답변", None)),
    ],
)
def test_parse_loop_note_splits_description_and_due(note, expected):
    assert parse_loop_note(note) == expected


@pytest.mark.parametrize(
    ("note", "rest", "evidence"),
    [
        (
            "보고서 보내기 @2026-10-12 15:00 (근거: 내일 3시까지 보고서 보내야 해)",
            "보고서 보내기 @2026-10-12 15:00",
            "내일 3시까지 보고서 보내야 해",
        ),
        ('결과 공유 (근거: "배포 끝나면 알려줄게")', "결과 공유", "배포 끝나면 알려줄게"),
        ("결과 공유 (근거: 배포 끝나면) @2026-10-12 15:00", "결과 공유 @2026-10-12 15:00", "배포 끝나면"),
        ("결과 공유 (근거:)", "결과 공유", None),
        ("결과 공유", "결과 공유", None),
    ],
)
def test_split_evidence_separates_quote_and_keeps_due_parsable(note, rest, evidence):
    assert split_evidence(note) == (rest, evidence)
    assert parse_loop_note(split_evidence(note)[0])[0] == parse_loop_note(rest)[0]


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        ([_loop("배포 결과 공유")], _loop("리뷰 답변")),
        ([_loop("배포 결과 공유", status="done"), _loop("배포 결과 공유", session="s2")], _loop("배포 결과 공유")),
    ],
)
def test_merge_loop_returns_new_when_no_open_same_session_match(existing, new):
    assert merge_loop(existing, new) is new


def test_merge_loop_fills_due_once():
    existing = _loop("배포 결과 공유 회의 준비")

    updated = merge_loop([existing], _loop("배포 결과 공유 회의 준비 및 진행", due=1000))

    assert updated is not None and updated.id == existing.id and updated.due_ms == 1000
    assert updated.description == existing.description
    assert merge_loop([updated], _loop("배포 결과 공유 회의 준비 및 진행", due=1000)) is None


def test_merge_loop_uses_similarities_by_id():
    existing = _loop("참석자 목록 확정")
    new = _loop("회의 참석자들의 최종 리스트 확정", due=1000)

    merged = merge_loop([existing], new, {existing.id: 0.9})

    assert merge_loop([existing], new) is new
    assert merged is not None and merged.id == existing.id and merged.due_ms == 1000


def test_expired_ids_closes_past_due_and_old_undated_open_loops():
    loops = [
        _loop("기한 지남", due=1_000),
        _loop("여유 안", due=9_000),
        _loop("오래된 기한 없음", created=0),
        _loop("최근 기한 없음", created=9_500),
        _loop("닫힌 것", due=1_000, status="done"),
    ]
    ids = {x.id: x.description for x in loops}

    with_age = [ids[i] for i in expired_ids(loops, now_ms=10_000, grace_ms=2_000, max_age_ms=5_000)]
    age_off = [ids[i] for i in expired_ids(loops, now_ms=10_000, grace_ms=2_000, max_age_ms=0)]

    assert with_age == ["기한 지남", "오래된 기한 없음"]
    assert age_off == ["기한 지남"]


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
def test_refers_to_matches_closing_note_to_its_loop(note, desc, hit):
    assert refers_to(note, desc) is hit


@pytest.mark.parametrize(
    ("note", "picked"), [("1", [0]), ("[2]", [1]), ("2번", [1]), ("[1] 아무 문구", [0]), ("9", [])]
)
def test_matching_ids_picks_by_shown_number(note, picked):
    shown = [_loop("분기 보고서 초안 제출"), _loop("리뷰 답변")]

    assert matching_ids(shown, [note]) == [shown[i].id for i in picked]


def test_matching_ids_picks_by_text_and_skips_closed():
    shown = [_loop("분기 보고서 초안 제출"), _loop("리뷰 답변", status="done")]

    assert matching_ids(shown, ["분기 보고서 초안 제출은 취소", "리뷰 답변"]) == [shown[0].id]


@pytest.mark.parametrize(
    ("note", "source", "evidence", "expected"),
    [
        ("분기 보고서 초안을 팀장님께 제출", "내일 오후 3시까지 분기 보고서 초안을 팀장님께 보내야 해", None, True),
        ("핵심 메시지 3가지 구조화 작업", "분기 보고서 초안 보내는 건 취소됐어", None, False),
        ("오늘 할 일 한 줄 요약", "분기 보고서 초안 보내는 건 취소됐어", None, False),
        # 문구만으로는 입력과 안 겹쳐 버려지던 약속을 근거 인용이 살린다
        ("결과 공유", "배포 끝나면 내가 알려줄게", None, False),
        ("결과 공유", "배포 끝나면 내가 알려줄게", "배포 끝나면 내가 알려줄게", True),
        # 회상된 기억에서 지어낸 근거는 입력에 없다
        ("핵심 메시지 구조화", "보고서는 취소됐어", "핵심 메시지 3가지 구조화 작업", False),
    ],
)
def test_grounded_requires_note_or_evidence_in_user_input(note, source, evidence, expected):
    assert grounded(note, source, evidence=evidence) is expected


@pytest.mark.parametrize(
    ("user_input", "picked"),
    [
        ("분기 보고서 초안 보내는 건 취소됐어. 안 챙겨도 돼", [0]),
        ("분기 보고서 초안 보내는 거 어떻게 돼가?", []),
        ("그건 취소됐어", []),
        ("보고서 분량은 그만큼이면 돼", []),
    ],
)
def test_cancelled_ids_needs_cancel_cue_and_target(user_input, picked):
    shown = [_loop("분기 보고서 초안 보냄"), _loop("리뷰 답변")]

    assert cancelled_ids(shown, user_input) == [shown[i].id for i in picked]
