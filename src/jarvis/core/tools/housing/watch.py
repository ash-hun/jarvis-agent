"""[core] 지난 조회 뒤 새로 올라온 LH, SH 공고 중 프로필로 신청 가능성이 있는 것만 알리는 housing_watch 도구."""

import os
import json
import asyncio
import hashlib
from typing import Any
from pathlib import Path
from datetime import date
from dataclasses import replace
from collections.abc import Callable

from jarvis.core.tools.housing.lh_notice import LhNoticeTool, Notice, build_queries, detail_url, resolve_region
from jarvis.core.tools.housing.rules import NO, OK, UNKNOWN, Rules, Verdict, load_rules, notice_access
from jarvis.core.tools.housing.profile import HousingProfile, ProfileStore, regions_or_home
from jarvis.core.tools.housing.sh_notice import BOARDS, ShNoticeTool, view_url
from jarvis.core.tools.housing.markup import deadline_label, parse_date
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.housing.fetch import FetchError, kst_today
from jarvis.core.tools.registry import JarvisTool, ToolContext
from jarvis.memory.scope import LOCAL_USER

TOOL_NAME = "housing_watch"
SEEN_DIR = "~/.jarvis/housing/seen"
# 본 공고 id 를 이만큼만 기억한다. 마감된 공고는 다시 공고중이 되지 않아 오래된 것부터 버려도 된다
SEEN_MAX = 2000
# 한 번에 이름을 적는 새 공고 수. 넘치면 수만 센다
MAX_LISTED = 10
OPEN_STATUS = "공고중"
ACCESS_LABEL = {OK: "높음", UNKNOWN: "확인 필요"}
# SH 는 서울 공고만 있다. 지역에 서울이나 전국이 있을 때만 본다
SH_REGION = "서울"
SH_CATEGORIES = ("임대", "분양")
# SH 게시판에는 상태 칸이 없어 제목 말로 짐작한 값이다(sh_notice.title_status)
SH_OPEN_STATUS = "모집/접수"
SH_PREFIX = "sh-"

TOOL_DESCRIPTION = (
    "지난번 housing_watch 뒤로 새로 올라온 LH 공고중 공고 중, 주거 프로필로 신청 가능성이 있는 것만 알린다."
    " 지역에 서울이나 전국이 있으면 SH(서울주택도시공사) 임대, 분양 게시판의 최신 모집 글도 본다."
    " 지역마다 본 공고를 기억해 같은 공고는 두 번 알리지 않는다."
    " 처음 부르면 지금 공고중인 것 중 신청 가능성이 있는 것을 전부 알리고, 그다음부터는 새 공고만 알린다."
    " quiet=true 면 새 공고가 없을 때 빈 글을 준다(스케줄 알림이 울리지 않는다)."
    " 매일 알림은 schedules 에 kind: tool, tool: housing_watch 작업으로 건다."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "regions": {"type": "string", "description": "지역. 쉼표로 여럿. 예: 서울,경기. 비우면 관심 지역(없으면 전국)"},
        "quiet": {"type": "boolean", "description": "새 공고가 없으면 빈 글(스케줄용)"},
    },
}


def watch_key(user_id: str, regions: list[str]) -> str:
    """자연 키: 사용자와 지역 묶음. 지역 순서가 달라도 같은 감시다."""
    raw = f"{user_id}|{','.join(sorted(set(regions)))}"
    return "hw_" + hashlib.sha1(raw.encode()).hexdigest()[:24]


def open_notices(found: list[Notice], today: date) -> list[Notice]:
    """마감이 지나지 않은 공고를 마감순으로, 같은 id 는 하나만."""
    unique: dict[str, Notice] = {}
    for n in found:
        close = parse_date(n.closes)
        if close is None or close >= today:
            unique.setdefault(n.id, n)
    return sorted(unique.values(), key=lambda n: parse_date(n.closes) or date.max)


def sh_notices(category: str, posts: list[Any]) -> list[Notice]:
    """SH 게시판 글을 공고로. 마감 칸이 없어 마감은 비우고, 모집으로 보이는 글만 남긴다."""
    return [
        Notice(f"{SH_PREFIX}{category}-{p.seq}", f"SH {category}", p.title, "서울특별시", p.registered, "", p.status)
        for p in posts
        if p.status == SH_OPEN_STATUS
    ]


def is_sh(nid: str) -> bool:
    return nid.startswith(SH_PREFIX)


def notice_url(nid: str) -> str:
    if is_sh(nid):
        category, _, seq = nid[len(SH_PREFIX):].partition("-")
        return view_url(BOARDS[category], seq)
    return detail_url(nid)


def pick_new(
    notices: list[Notice], seen: list[str], rules: Rules, profile: HousingProfile
) -> list[tuple[Notice, Verdict]]:
    """본 적 없는 공고 중 신청 가능성이 낮지 않은 것과 그 판정."""
    known = set(seen)
    picked = []
    for n in notices:
        if n.id in known:
            continue
        # SH 는 유형 칸이 없어 제목(행복주택, 국민임대 등)으로 공고 유형 기준을 고른다
        verdict = notice_access(rules, n.title if is_sh(n.id) else n.kind, n.title, profile)
        if verdict.status != NO:
            picked.append((n, verdict))
    return picked


def remember(seen: list[str], notices: list[Notice]) -> list[str]:
    """본 공고 목록에 이번 공고를 더한다. 이미 있는 id 는 그대로, 넘치면 오래된 것부터 버린다. 두 번 더해도 같다."""
    merged = list(dict.fromkeys([*seen, *(n.id for n in notices)]))
    return merged[-SEEN_MAX:]


def render(regions: list[str], picked: list[tuple[Notice, Verdict]], today: date, first: bool = False) -> str:
    what = "지금 공고중인 공고 중 신청 가능성이 있는 것" if first else "새 공고"
    lines = [f"{what} {len(picked)}건 ({', '.join(regions)}). 마감은 KST {today.isoformat()} 기준"]
    for n, verdict in picked[:MAX_LISTED]:
        if is_sh(n.id):
            label, when = "SH", f"등록 {n.posted} | 마감 공고문 확인"
        else:
            label, when = deadline_label(parse_date(n.closes), today), f"마감 {n.closes or '-'}"
        lines.append(
            f"- [{label}] {n.title}\n  유형 {n.kind} | 지역 {n.region} | {when}"
            # 디스코드는 목록 안의 들여쓴 줄바꿈을 지워 링크가 앞 글자에 붙는다. 구분자 뒤 같은 줄에 둔다
            f" | 신청 가능성 {ACCESS_LABEL[verdict.status]}: {'; '.join(verdict.reasons)} | {notice_url(n.id)}"
        )
    if len(picked) > MAX_LISTED:
        lines.append(f"\n그 밖에 {len(picked) - MAX_LISTED}건. 전부 보려면 lh_notice, sh_notice 로 찾는다")
    return "\n".join(lines)


class SeenStore:
    """감시 키마다 본 공고 id 를 JSON 파일 하나에 둔다. 같은 키는 늘 같은 파일을 덮는다."""

    def __init__(self, root: str = SEEN_DIR) -> None:
        self._root = Path(root).expanduser()

    def _path(self, key: str) -> Path:
        return self._root / f"{key}.json"

    def load(self, key: str) -> list[str] | None:
        """처음 보는 키면 None."""
        path = self._path(key)
        if not path.exists():
            return None
        ids: list[str] = json.loads(path.read_text(encoding="utf-8"))["ids"]
        return ids

    def save(self, key: str, regions: list[str], ids: list[str]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(key).with_suffix(".tmp")
        body = {"regions": sorted(set(regions)), "ids": ids}
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        # 쓰다 죽어도 이전 파일이 남는다
        os.replace(tmp, self._path(key))


class HousingWatchTool(JarvisTool):
    """읽고 기록만 한다. 알림은 부른 쪽(스케줄러)이 보낸다."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "sequential"

    def __init__(
        self,
        notices: LhNoticeTool,
        seen: SeenStore,
        today: Callable[[], date] = kst_today,
        profiles: ProfileStore | None = None,
        rules: Callable[[], Rules] = load_rules,
        sh: ShNoticeTool | None = None,
    ) -> None:
        self._notices = notices
        self._sh = sh
        self._seen = seen
        self._today = today
        self._profiles = profiles
        self._rules = rules

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        today = self._today()
        scope = getattr(context, "scope", None)
        user = (scope.user_id if scope is not None else None) or LOCAL_USER
        profile = await self._profiles.get(user) if self._profiles is not None else HousingProfile()
        regions = regions_or_home(params.get("regions"), profile)
        unknown = [r for r in regions if resolve_region(r) is None]
        if unknown:
            return _result(tool_call_id, f"모르는 지역: {', '.join(unknown)}", True)
        try:
            notices = open_notices(await self._search(regions, today), today)
        except (FetchError, ValueError) as exc:
            return _result(tool_call_id, f"LH 조회 실패: {exc}", True)
        sh_note = ""
        seoul = resolve_region(SH_REGION)
        if self._sh is not None and any(resolve_region(r) in ("", seoul) for r in regions):
            try:
                notices += await self._sh_search(self._sh)
            except (FetchError, ValueError) as exc:
                # SH 가 막혀도 LH 보고는 보낸다. SH 글은 다음 조회 때 새 공고로 온다
                sh_note = f"\n\nSH 조회 실패: {exc}"
        key = watch_key(user, regions)
        seen = self._seen.load(key)
        # 처음이면 본 것이 없으니 지금 공고중인 것이 모두 새 공고다
        picked = pick_new(notices, seen or [], self._rules(), profile)
        # ponytail: 알리기 전에 본 것으로 적는다(알림이 실패하면 그 공고는 다시 오지 않는다),
        # 놓친 알림이 보이면 알림이 간 뒤에 기록하도록 바꾼다
        self._seen.save(key, regions, remember(seen or [], notices))
        if picked:
            text = render(regions, picked, today, first=seen is None)
            if seen is None:
                text += "\n\n다음부터는 새로 올라온 공고만 알린다."
        else:
            text = "" if params.get("quiet") else f"지난번 뒤로 새로 알릴 공고가 없다({', '.join(regions)})."
        return _result(tool_call_id, (text + sh_note).strip())

    async def _sh_search(self, sh: ShNoticeTool) -> list[Notice]:
        found: list[Notice] = []
        for category in SH_CATEGORIES:
            # ponytail: 게시판마다 첫 쪽(최신 10건)만 본다, 하루 10건 넘게 올라오면 놓치니 그때 쪽을 넘긴다
            found.extend(sh_notices(category, await sh.latest(category)))
        return found

    async def _search(self, regions: list[str], today: date) -> list[Notice]:
        found: list[Notice] = []
        for region in regions:
            queries, reason = build_queries({"region": region, "status": OPEN_STATUS})
            if reason is not None:
                raise ValueError(reason)
            for _, _, notices in await self._notices.search([replace(q, all_pages=True) for q in queries], today):
                found.extend(notices)
        return found


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TOOL_NAME, content=[TextContent(text=text)], is_error=is_error
    )
