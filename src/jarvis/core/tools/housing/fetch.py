"""[core] 공고 게시판 HTML 을 가져오는 HTTP 경계와 KST 오늘 날짜. 둘 다 도구 밖에서 주입할 수 있다."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import httpx

# 게시판이 봇 UA 를 막는 일이 있어 브라우저 UA 를 쓴다(공개 페이지 읽기만 한다)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) jarvis-karen/1.0"
TIMEOUT_SEC = 20.0
KST_OFFSET = timedelta(hours=9)

# (url, query) → 본문 HTML. 실패하면 FetchError
Fetch = Callable[[str, dict[str, str]], Awaitable[str]]


class FetchError(Exception):
    """게시판에 닿지 못했거나 오류 응답을 받았다. 메시지를 그대로 도구 결과로 돌려준다."""


async def fetch_html(url: str, query: dict[str, str]) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SEC, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url, params=query)
    except httpx.HTTPError as exc:
        raise FetchError(f"{url} 에 닿지 못했다: {exc}") from exc
    if response.status_code != httpx.codes.OK:
        raise FetchError(f"{url} 가 HTTP {response.status_code} 로 답했다")
    return response.text


def kst_today() -> date:
    """마감 판정의 기준일. 서버 시간대와 상관없이 한국 날짜다."""
    return (datetime.now(UTC) + KST_OFFSET).date()
