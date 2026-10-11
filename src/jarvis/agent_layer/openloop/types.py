from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MIN_CONTAINMENT_CHARS = 6  # 이보다 짧은 조각의 포함은 우연이 많다
# 글자 bigram Jaccard. 실제로 쌓인 바꿔 말한 중복은 0.43~0.85, 다른 약속끼리는 0.21 이하였다
SIMILAR_JACCARD = 0.4
# 닫는 말("~는 취소됐어")은 대상 약속에 말이 덧붙어 Jaccard 가 묽어진다. 짧은 쪽 기준 겹침으로 본다.
# 실측: 취소 문장과 그 약속 0.54~0.6, 관계없는 약속 0.12 이하
CLOSE_OVERLAP = 0.5
# 사고가 open_loops 항목 끝에 붙이는 기한 표기: "회의 준비 @2026-10-12 10:00"
# 사고에 보여준 약속 번호. 닫을 약속을 번호로 받는다: "1", "[1]", "1번", "[1] 회의 준비"
LOOP_REF = re.compile(r"\s*(?:\[(\d+)\]|(\d+)\s*번?\s*$)")
# 새 약속의 글자 bigram 중 이 비율 이상이 사용자 입력에 있어야 저장한다. 회상된 기억에서 옮겨 적은 약속은 0 이었다
GROUNDED_OVERLAP = 0.2
# 사용자가 약속을 거둘 때 쓰는 말(공백 뺀 형태). 사고 모델이 closed_loops 를 놓쳐도 이 말이 약속을 가리키면 닫는다.
# 완료 표현("보냈어", "다 했어")은 질문과 구분이 안 돼 넣지 않는다. "그만큼" 과 겹치는 "그만" 단독도 뺀다.
CANCEL_CUES = ("취소", "안해도", "하지마", "하지말", "그만해", "그만두", "그만하", "필요없", "안챙겨")
DUE_SUFFIX = re.compile(r"\s*@\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})\s*$")

LoopStatus = Literal["open", "done", "dismissed", "expired"]
LOOP_STATUSES: tuple[str, ...] = ("open", "done", "dismissed", "expired")


@dataclass(frozen=True)
class LoopExpiry:
    """기한이 지난 약속을 닫는 규칙. grace_ms 는 기한 뒤 여유, max_age_ms 는 기한 없는 약속의 수명(0 이면 끔)."""

    grace_ms: int
    max_age_ms: int


class OpenLoop(BaseModel):
    """추적 중인 약속/미완 작업 1건 (Tier 2).

    사용자가 흘린 "나중에 ~할게", "~ 확인 부탁" 같은 미완 obligation을 추적한다.
    상태 전이: open → done | dismissed | expired.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    description: str
    status: LoopStatus = "open"
    origin_session: str | None = None
    # 기한(epoch ms). reflection 이 [지금]과 함께 보고 상기하고, 지나고 한참 뒤에는 expired 로 닫힌다.
    due_ms: int | None = None
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = Field(default_factory=lambda: int(time.time() * 1000))


def normalize_description(text: str) -> str:
    """중복 판정용 정규화 — 공백 정리 + 소문자."""
    return " ".join(text.split()).lower()


def _bigrams(text: str) -> set[str]:
    compact = "".join(text.split()).lower()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def same_loop(a: str, b: str) -> bool:
    """같거나, 짧은 쪽이 긴 쪽에 통째로 들어가거나, 글자 bigram 이 충분히 겹치면 같은 약속으로 본다."""
    x, y = normalize_description(a), normalize_description(b)
    if not x or not y:
        return False
    if x == y:
        return True
    short, long = sorted((x, y), key=len)
    if len(short) >= MIN_CONTAINMENT_CHARS and short in long:
        return True
    # ponytail: 글자 겹침만 본다("참석자 목록" ≠ "최종 리스트"), 단어가 다른 같은 약속이 계속 쌓이면 임베딩 유사도로
    bx, by = _bigrams(x), _bigrams(y)
    return bool(bx and by) and len(bx & by) / len(bx | by) >= SIMILAR_JACCARD


def refers_to(note: str, description: str) -> bool:
    """닫는 말이 그 약속을 가리키는지. same_loop 보다 느슨하다(사고가 닫으라고 짚은 경우에만 쓴다)."""
    if same_loop(note, description):
        return True
    bn, bd = _bigrams(note), _bigrams(description)
    return bool(bn and bd) and len(bn & bd) / min(len(bn), len(bd)) >= CLOSE_OVERLAP


def parse_loop_note(note: str) -> tuple[str, int | None]:
    """사고가 쓴 "설명 @YYYY-MM-DD HH:MM" 을 설명과 기한(epoch ms)으로 나눈다. 시각은 프로세스 로컬 시간대."""
    m = DUE_SUFFIX.search(note)
    if m is None:
        return note.strip(), None
    try:
        due = datetime.strptime(f"{m.group(1)} {int(m.group(2)):02d}:{m.group(3)}", "%Y-%m-%d %H:%M")
    except ValueError:
        return note[: m.start()].strip(), None
    return note[: m.start()].strip(), int(due.timestamp() * 1000)


def merge_loop(open_loops: list[OpenLoop], new: OpenLoop) -> OpenLoop | None:
    """새 약속을 넣을 때 쓸 레코드를 정한다. 같은 세션의 열린 같은 약속이 있으면 그걸 갱신하고,
    바뀔 게 없으면 None. 두 번 불러도 두 번째는 None 이라 저장이 한 번만 일어난다."""
    for existing in open_loops:
        if existing.status != "open" or existing.origin_session != new.origin_session:
            continue
        if not same_loop(existing.description, new.description):
            continue
        if new.due_ms is None or new.due_ms == existing.due_ms:
            return None
        return existing.model_copy(update={"due_ms": new.due_ms, "updated_at": new.updated_at})
    return new


def matching_ids(shown: list[OpenLoop], notes: list[str]) -> list[str]:
    """사고가 닫으라고 짚은 항목의 id. shown 은 사고에 [1] 부터 번호를 붙여 보여준 순서다.
    번호가 있으면 번호로, 없으면 문구가 가리키는 약속으로 찾는다."""
    ids: list[str] = []
    for note in notes:
        ref = LOOP_REF.match(note)
        if ref is not None:
            index = int(ref.group(1) or ref.group(2)) - 1
            picked = [shown[index]] if 0 <= index < len(shown) else []
        else:
            picked = [loop for loop in shown if refers_to(note, loop.description)]
        ids.extend(loop.id for loop in picked if loop.status == "open" and loop.id not in ids)
    return ids


def cancelled_ids(shown: list[OpenLoop], user_input: str) -> list[str]:
    """사용자 입력이 거두는 말이면, 그 입력이 가리키는 열린 약속의 id."""
    compact = "".join(user_input.split())
    if not any(cue in compact for cue in CANCEL_CUES):
        return []
    return [loop.id for loop in shown if loop.status == "open" and refers_to(user_input, loop.description)]


def grounded(note: str, source: str) -> bool:
    """새 약속이 사용자 입력에서 나왔는지. 작은 모델은 회상된 기억 속 약속을 새로 흘린 것처럼 옮겨 적는다."""
    # ponytail: 글자 겹침만 본다(입력과 안 겹치게 바꿔 말한 약속은 버린다), 놓치는 약속이 많으면 사고가 근거 문장도 내게
    bn = _bigrams(note)
    return bool(bn) and len(bn & _bigrams(source)) / len(bn) >= GROUNDED_OVERLAP


def expired_ids(open_loops: list[OpenLoop], now_ms: int, grace_ms: int, max_age_ms: int) -> list[str]:
    """기한이 grace 만큼 지났거나, 기한 없이 max_age 보다 오래된 열린 항목의 id. 0 이면 그 규칙은 끈다."""
    ids = []
    for loop in open_loops:
        if loop.status != "open":
            continue
        if loop.due_ms is not None:
            if now_ms > loop.due_ms + grace_ms:
                ids.append(loop.id)
        elif max_age_ms > 0 and now_ms - loop.created_at > max_age_ms:
            ids.append(loop.id)
    return ids
