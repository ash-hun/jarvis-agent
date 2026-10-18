"""[scripts] 회상 품질(후보, 섬광 기억, 조사, 지칭, 되뇌기)을 같은 시나리오로 재서 results.json 에 쓴다."""

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from jarvis.core.slash.remember_cmd import make_remember_handler
from jarvis.memory.eval.fake_embedder import FakeEmbedder
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope, current_scope
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.model_layer.types import AssistantMessage, TextContent, UserMessage

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "memory_recall"
# 섬광 기억 실험에서 큰 사건보다 나중에 쌓인, 같은 낱말의 사소한 일화 수
DISTRACTORS = [0, 3, 6, 9, 12, 20, 40]
# 고정 블록 실험에서 핵심 사실보다 나중에 쌓인 사소한 의미 사실 수(fixed_facts=3, 후보 풀 12)
NEWER_FACTS = [0, 4, 8, 12, 20, 40]
UNRELATED_TURNS = 10
LATENCY_ITEMS = 2000
LATENCY_QUERIES = 200
LATENCY_WARMUP = 20  # 커넥션 풀과 마이그레이션, 첫 쿼리 계획이 지연에 섞이지 않도록 버리는 호출 수
TOP_K = 3
CTX = {"session_id": "s1", "user_id": "u1", "agent_id": "main"}
SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
NOW = datetime(2026, 10, 18, 12, 0)

SALIENT = [
    ("여행", "여행: 땅콩 알레르기로 응급실에 실려 갔다", "여행: 사진 {i}장 정리"),
    ("이사", "이사: 계약금을 사기당해 경찰에 신고했다", "이사: 박스 {i}개 주문"),
    ("면접", "면접: 최종 합격 통보를 받았다", "면접: 예상 질문 {i}번 정리"),
    ("병원", "병원: 수술 날짜가 확정됐다", "병원: 주차 {i}시간"),
    ("차", "차: 고속도로에서 사고가 났다", "차: 세차 {i}회"),
    ("결혼", "결혼: 상견례 날짜를 정했다", "결혼: 청첩장 시안 {i}번"),
    ("투자", "투자: 손실이 커서 전부 정리했다", "투자: 시세 {i}번 확인"),
    ("강아지", "강아지: 보리가 수술을 받았다", "강아지: 산책 {i}회"),
]
CORE = ["이름: 재훈", "알레르기: 땅콩", "생일: 3월 2일", "직장: 브레인크루",
        "거주지: 서울", "반려견: 보리", "혈액형: A", "차량: 아반떼"]
PARTICLES = [
    ("거주지: 서울", "서울에서 주말에 뭐 하지"), ("반려견: 보리", "보리가 밥을 안 먹어"),
    ("직장: 브레인크루", "브레인크루에 뭐 가져가지"), ("알레르기: 땅콩", "땅콩은 먹어도 되나"),
    ("차량: 아반떼", "아반떼를 언제 정비하지"), ("취미: 클라이밍", "클라이밍이 끝나고 뭐 하지"),
    ("선호 음료: 커피", "커피를 하루에 몇 잔 마셨지"), ("주치의: 김원장", "김원장한테 예약해"),
    ("헬스장: 강남점", "강남점까지 얼마나 걸려"), ("목표: 마라톤", "마라톤으로 뭘 준비하지"),
]
# (지난 주제 질문, 그 답, 지칭만 있는 다음 발화, 장기 기억에 있던 관련 일화)
DEICTIC = [
    ("배포 일정 정리해줘", "금요일 배포로 정리했다", "그거 다시 해줘", "배포: 스테이징은 금요일에 막아 둔다"),
    ("예산 계산해줘", "총예산 2억으로 계산했다", "아까 그거 다시 보여줘", "예산: 대출 금리는 4% 로 가정한다"),
    ("회의록 요약해줘", "세 줄로 요약했다", "그거 메일로 보내", "회의록: 팀장은 세 줄 요약을 선호한다"),
    ("논문 찾아줘", "메모리 관련 논문 다섯 편", "그거 정리해줘", "논문: 정리는 표 형식으로 한다"),
    ("운동 계획 세워줘", "주 3회 클라이밍", "그거 캘린더에 넣어", "운동: 무릎 때문에 달리기는 뺀다"),
    ("이사 체크리스트 만들어줘", "열 가지 항목", "그거 다시", "이사: 인터넷 이전 신청을 늦게 해서 고생했다"),
    ("면접 질문 뽑아줘", "예상 질문 열 개", "이거 더 늘려줘", "면접: 기술 면접은 시스템 설계 위주였다"),
    ("여행 숙소 찾아줘", "후보 세 곳", "방금 그거 예약해", "여행: 숙소는 역 근처를 선호한다"),
]
# (지난 주제 질문, 그 답, "/remember" 로 남긴 지칭 문장, 며칠 뒤 주제로 묻는 질의)
REFERENT = [
    ("커밋 메시지 규칙 정해줘", "제목 50자, 본문은 이유만", "그거 앞으로 계속 써", "커밋 메시지"),
    ("회의록 형식 정해줘", "결정, 담당, 기한 세 칸", "그 방식 기억해", "회의록 형식"),
    ("코드 리뷰 기준 정해줘", "보안, 멱등성, 테스트 순서", "이거 기억해", "코드 리뷰"),
    ("보고서 톤 정해줘", "결론 먼저, 숫자는 표로", "그거 기억해 둬", "보고서 톤"),
    ("운동 루틴 짜줘", "월수금 클라이밍", "아까 그거 기억해", "운동 루틴"),
    ("식단 정해줘", "저녁은 탄수화물 줄이기", "그거 앞으로 지킬게", "식단"),
    ("독서 계획 세워줘", "한 달에 두 권", "그 계획 기억해", "독서 계획"),
    ("예산 원칙 정해줘", "고정비는 소득의 30%", "그거 기억해", "예산 원칙"),
]
# 질의 낱말 셋 중 하나만 큰 사건과 겹친다. 큰 사건이 끼어들면 과잉일반화다
OVERREACH = [(salient, f"{key} 계획 메모") for key, salient, _ in SALIENT]


def _u(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


def _a(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], timestamp=0)


def _ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


async def salient_curve() -> dict[str, float]:
    curve: dict[str, float] = {}
    for n in DISTRACTORS:
        hits = 0
        for key, salient, trivial in SALIENT:
            memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
            await memory.remember(salient, "session_end", SCOPE, importance=1.0, created_at=_ago(days=200))
            for i in range(n):
                await memory.remember(trivial.format(i=i), "session_end", SCOPE, importance=0.1,
                                      created_at=_ago(hours=i + 1))
            hits += any(i.content == salient for i in await memory.recall(key, SCOPE, limit=TOP_K))
        curve[str(n)] = hits / len(SALIENT)
    return curve


async def core_fact_curve() -> dict[str, float]:
    curve: dict[str, float] = {}
    for n in NEWER_FACTS:
        hits = 0
        for core in CORE:
            memory = MemoryService(InMemoryItemStore(), fixed_facts=3)
            # 규칙 기본값이 아니라 후보 선정을 재려고 전후 모두 같은 importance 로 쓴다
            await memory.remember(core, "explicit", SCOPE, importance=0.9, created_at=_ago(days=100))
            for i in range(n):
                await memory.remember(f"사소한 취향{i}: 메모 {i}", "extracted", SCOPE, importance=0.3,
                                      created_at=_ago(hours=i + 1))
            hits += any(i.content == core for i in await memory.fixed_facts(SCOPE))
        curve[str(n)] = hits / len(CORE)
    return curve


async def particle_rate() -> float:
    hits = 0
    for fact, query in PARTICLES:
        memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
        await memory.remember(fact, "explicit", SCOPE)
        hits += any(i.content == fact for i in await memory.recall(query, SCOPE, limit=TOP_K))
    return hits / len(PARTICLES)


async def deictic_rate() -> float:
    hits = 0
    for question, answer, follow_up, episode in DEICTIC:
        memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
        await memory.remember(episode, "session_end", SCOPE, created_at=_ago(days=3))
        out = await memory.observe([_u(question), _a(answer), _u(follow_up)], CTX)
        hits += any(isinstance(m.content, str) and m.content.startswith("[장기 기억]") and episode in m.content
                    for m in out)
    return hits / len(DEICTIC)


class _Repo:
    def __init__(self, messages: list) -> None:  # type: ignore[type-arg]
        self._messages = messages

    async def get_messages(self, session_id: str) -> list:  # type: ignore[type-arg]
        return self._messages


async def referent_rate() -> float:
    hits = 0
    for question, answer, note, later in REFERENT:
        memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
        try:
            handler = make_remember_handler(memory, _Repo([_u(question), _a(answer)]))  # type: ignore[call-arg]
        except TypeError:  # 지칭을 모르는 이전 코드는 session_repo 를 받지 않는다
            handler = make_remember_handler(memory)
        token = current_scope.set(SCOPE)
        try:
            await handler(note)
        finally:
            current_scope.reset(token)
        hits += any(i.content == note for i in await memory.recall(later, SCOPE, limit=TOP_K))
    return hits / len(REFERENT)


async def rehearsal_inflation() -> float:
    """주제와 무관한 턴만 이어질 때 고정 사실 하나가 받는 되뇌기 횟수 평균."""
    memory = MemoryService(InMemoryItemStore(), fixed_facts=3)
    for fact in CORE[:3]:
        await memory.remember(fact, "explicit", SCOPE)
    for _ in range(UNRELATED_TURNS):
        await memory.observe([_u("오늘 날씨 어때")], CTX)
    counts = (await memory.working_state(SCOPE)).rehearsal
    return sum(counts.values()) / 3


async def overreach_rate() -> float:
    intrusions = 0
    for salient, query in OVERREACH:
        memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
        await memory.remember(salient, "session_end", SCOPE, importance=1.0, created_at=_ago(days=200))
        for i in range(5):
            await memory.remember(f"{query.split()[0]} 계획 메모 {i}", "session_end", SCOPE, importance=0.1,
                                  created_at=_ago(hours=i + 1))
        intrusions += any(i.content == salient for i in await memory.recall(query, SCOPE, limit=TOP_K))
    return intrusions / len(OVERREACH)


async def postgres_latency() -> dict[str, float]:
    """pgvector 컨테이너에 일화 LATENCY_ITEMS 개를 넣고 recall 과 fixed_facts 의 지연(ms)을 잰다."""
    from testcontainers.postgres import PostgresContainer

    from jarvis.memory.stores.postgres import PostgresItemStore

    words = [key for key, _, _ in SALIENT]
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        store = PostgresItemStore(dsn=dsn, dimensions=FakeEmbedder.dimensions)
        memory = MemoryService(store, embedder=FakeEmbedder(), fixed_facts=3)
        for i in range(LATENCY_ITEMS):
            word = words[i % len(words)]
            await memory.remember(f"{word}: 기록 {i}", "session_end", SCOPE, importance=(i % 10) / 10,
                                  created_at=_ago(hours=i))
        for i in range(20):
            await memory.remember(f"사실{i}: 값 {i}", "explicit", SCOPE)
        for i in range(LATENCY_WARMUP):
            await memory.recall(f"{words[i % len(words)]} 기록", SCOPE, limit=TOP_K)
            await memory.fixed_facts(SCOPE)
        recall_ms, fixed_ms = [], []
        for i in range(LATENCY_QUERIES):
            start = time.perf_counter()
            await memory.recall(f"{words[i % len(words)]} 기록", SCOPE, limit=TOP_K)
            recall_ms.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            await memory.fixed_facts(SCOPE)
            fixed_ms.append((time.perf_counter() - start) * 1000)
        await store.close()
    return {
        "recall_p50_ms": round(statistics.median(recall_ms), 2),
        "recall_p95_ms": round(statistics.quantiles(recall_ms, n=20)[-1], 2),
        "fixed_p50_ms": round(statistics.median(fixed_ms), 2),
    }


async def measure(with_postgres: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "salient_hit_at_3": await salient_curve(),
        "core_fact_kept": await core_fact_curve(),
        "particle_hit_at_3": await particle_rate(),
        "deictic_recall": await deictic_rate(),
        "referent_recall": await referent_rate(),
        "rehearsal_per_fixed_fact": await rehearsal_inflation(),
        "overreach_rate": await overreach_rate(),
    }
    if with_postgres:
        result["postgres"] = await postgres_latency()
    return result


def write(label: str, result: dict[str, object]) -> None:
    """같은 label 의 같은 지표는 덮어쓴다. --postgres 없이 돌리면 지난번 지연 값은 그대로 둔다."""
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data.setdefault(KEY, {}).setdefault(label, {}).update(result)
    # 파일의 기존 서식(indent 1, 끝 줄바꿈 없음)을 지켜 다른 실험 항목에 diff 가 생기지 않게 한다
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="before 또는 after. results.json 의 memory_recall 아래 키")
    parser.add_argument("--postgres", action="store_true", help="pgvector 컨테이너로 지연도 잰다(Docker 필요)")
    parser.add_argument("--dry-run", action="store_true", help="results.json 에 쓰지 않고 출력만")
    args = parser.parse_args()
    result = asyncio.run(measure(args.postgres))
    print(json.dumps(result, ensure_ascii=False), file=sys.stdout)
    if not args.dry_run:
        write(args.label, result)


if __name__ == "__main__":
    main()
