"""memory 기능의 출처 복원: 사실의 출처 일화 고르기와 출처 발췌, 회상 줄 표시."""

from jarvis.memory.long_term.fact_source import nearest_episode, pick_source, source_excerpt, with_source
from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def _episode(content: str, embedding: list[float] | None = None) -> MemoryItem:
    return MemoryItem(content=content, kind=MemoryKind.EPISODIC, scope=SCOPE, embedding=embedding)


def test_pick_source_takes_the_episode_with_most_fact_words():
    first, second = _episode("주말에 등산 갔다"), _episode("부산으로 이사했고 해운대 근처에 산다")

    assert pick_source("거주지: 부산 해운대", [first, second]) is second


def test_pick_source_without_shared_words_is_none():
    assert pick_source("residence: Busan", [_episode("주말에 등산 갔다")]) is None
    assert pick_source("거주지: 부산", []) is None


def test_nearest_episode_falls_back_to_vectors_and_skips_unembedded():
    near, far = _episode("I moved to Busan", [1.0, 0.0]), _episode("hiking", [0.0, 1.0])

    assert nearest_episode([0.9, 0.1], [far, near, _episode("no vector")]) is near
    assert nearest_episode([0.9, 0.1], [_episode("no vector")]) is None


def test_source_excerpt_centers_on_the_matching_sentence_within_limit():
    text = "오늘 날씨가 좋다. 나는 땅콩 알레르기가 있어서 조심한다. 저녁은 파스타였다. " + "잡담. " * 200

    excerpt = source_excerpt("알레르기: 땅콩", text, limit=60)

    assert "땅콩 알레르기" in excerpt and len(excerpt) <= 60


def test_source_excerpt_of_empty_text_is_empty():
    assert source_excerpt("알레르기: 땅콩", "  \n ") == ""


def test_with_source_adds_a_line_only_when_an_excerpt_exists():
    assert with_source("알레르기: 땅콩", "땅콩 알레르기가\n있다") == "알레르기: 땅콩\n  ↳ 출처: 땅콩 알레르기가 있다"
    assert with_source("알레르기: 땅콩", None) == "알레르기: 땅콩"
