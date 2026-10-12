"""[app] 최상위 에이전트끼리 일을 맡기고 묻는 ask_agent 도구와, 에이전트 쌍마다 이어지는 대화 세션 규칙."""

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from jarvis.agent_layer.openloop.types import same_loop
from jarvis.common.logger import get_logger
from jarvis.core.session import SessionBusy
from jarvis.core.tools.registry import JarvisTool, ToolContext
from jarvis.memory.scope import MAIN_AGENT, current_scope
from jarvis.model_layer.types import AssistantMessage, TextContent, ToolResultMessage

if TYPE_CHECKING:
    from jarvis.app.agent_registry import AgentRegistry
    from jarvis.core.session import AgentSession

ASK_AGENT_TOOL = "ask_agent"
PEER_SESSION_PREFIX = "peer"
# A 가 B 에게, B 가 다시 A 에게 묻는 데까지. 더 깊으면 서로 미루는 고리가 되기 쉬워 끊는다
MAX_PEER_HOPS = 3
# 받는 쪽이 도구를 여러 번 쓰는 정보 수집을 기다린다
PEER_TIMEOUT_SEC = 300.0
# 받는 쪽이 백그라운드로 답할 때(Dual-Channel) 끝났는지 보는 간격
PEER_POLL_SEC = 0.2
# 요청 끝에 붙는 규칙. 실서버에서 gemma4:e4b 가 위임받은 세션에서 도구를 부르지 않고 조회한 척 답하는 것을 봤다
PEER_REQUEST_RULE = "받은 일이다. 필요하면 가진 도구를 먼저 부르고, 도구 결과에 있는 것만 답한다."

# (받는 에이전트 id, 대화 세션 id, 부른 세션 id) → 받는 쪽 세션. 화면마다 여는 방식이 다르다(web 은 세션 목록에 띄운다)
PeerOpener = Callable[[str, str, str | None], Awaitable["AgentSession"]]

# 이 턴이 지나온 에이전트들. 처음 부른 쪽부터. 받는 쪽 세션의 도구 호출까지 contextvar 로 이어진다
peer_chain: ContextVar[tuple[str, ...]] = ContextVar("jarvis_peer_chain", default=())
# 이 턴이 받은 요청 문구. 받는 쪽이 같은 일을 보낸 쪽에 되돌리는지 가린다
peer_request: ContextVar[str] = ContextVar("jarvis_peer_request", default="")

logger = get_logger(__name__)


def peer_session_id(caller: str, target: str) -> str:
    """부른 쪽과 받는 쪽 쌍마다 세션 하나. 같은 쌍은 앞 대화를 이어 가고, 다시 열어도 같은 세션이다."""
    return f"{PEER_SESSION_PREFIX}-{caller}-{target}"


def peer_request_text(caller_name: str, message: str) -> str:
    """받는 쪽 세션에 들어가는 사용자 메시지. 누가 보냈는지와 지킬 규칙을 붙인다."""
    return f"[{caller_name} 의 요청] {message}\n({PEER_REQUEST_RULE})"


def refusal(
    agent_ids: list[str],
    chain: tuple[str, ...],
    caller: str,
    target: str,
    message: str,
    received: str = "",
) -> str | None:
    """보내지 않을 이유. 보내도 되면 None. 순수 함수라 규칙을 따로 시험한다.

    received 는 caller 가 받은 요청이다. 그 요청을 보낸 에이전트에게 거의 같은 일을 되돌리면 막는다.
    작은 모델(gemma4:e4b)이 받은 일을 그대로 되돌려 서로 미루는 것을 실서버에서 봤다.
    """
    if not message:
        return "message 가 비어 있다"
    if target not in agent_ids:
        return f"모르는 에이전트: {target} (있는 에이전트: {', '.join(agent_ids)})"
    if target == caller:
        return "자기 자신에게는 물을 수 없다"
    if len(chain) >= MAX_PEER_HOPS:
        return f"에이전트 사이 질문이 너무 깊다({' → '.join(chain)}). 지금 아는 것으로 답한다"
    if len(chain) >= 2 and target == chain[-2] and received and same_loop(message, received):
        return "받은 일을 보낸 에이전트에게 되돌릴 수 없다. 가진 도구로 직접 처리해 답한다"
    return None


async def ask(session: "AgentSession", text: str) -> str:
    """받는 쪽 세션에 한 턴을 보내고 답 텍스트를 받는다. 백그라운드로 답하면 끝날 때까지 기다려 저장소에서 읽는다."""
    reply = await session.prompt(text)
    if reply is None:
        while session.is_running:
            await asyncio.sleep(PEER_POLL_SEC)
        history = await session._session_repo.get_messages(session._session_id)
        reply = next((m for m in reversed(history) if isinstance(m, AssistantMessage)), None)
    return reply.text().strip() if reply is not None else ""


class AskAgentTool(JarvisTool):
    """같은 팀의 다른 최상위 에이전트에게 일을 맡기고 답을 받는다.

    JARVIS 가 총괄할 때와 에이전트끼리 되물을 때 같이 쓴다.
    """

    execution_mode: str = "sequential"

    def __init__(self, agents: "AgentRegistry", opener: PeerOpener) -> None:
        self.name = ASK_AGENT_TOOL
        self._agents = agents
        self._opener = opener
        roster = "\n".join(
            f"- {p.agent_id}: {p.name}{' (팀 총괄)' if p.is_main else ''}"
            + (f": {p.description}" if p.description else "")
            for p in agents.profiles()
        )
        self.description = (
            "같은 팀의 다른 에이전트에게 일을 맡기거나 묻고 그 답을 받는다."
            " 자기 분야가 아닌 일은 맡은 에이전트에게 묻는다."
            " 받는 쪽은 지금 대화를 모르므로 message 에 필요한 맥락을 담는다."
            " 자기 자신에게는 묻지 않는다. 다른 에이전트에게서 받은 일은 직접 처리해 답하고,"
            " 그 일을 보낸 에이전트에게 되돌려 보내지 않는다. 꼭 필요한 정보만 되묻는다.\n팀:\n" + roster
        )
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "enum": agents.ids(), "description": "받을 에이전트 id"},
                "message": {"type": "string", "description": "맡길 일이나 질문"},
            },
            "required": ["agent", "message"],
        }

    def set_opener(self, opener: PeerOpener) -> None:
        """받는 쪽 세션을 여는 방식을 바꾼다. Web 은 기동 때 세션 목록과 승인 화면에 잇는 opener 로 바꾼다."""
        self._opener = opener

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        scope = getattr(context, "scope", None) or current_scope.get()
        caller = scope.agent_id if scope is not None else MAIN_AGENT
        target = str(params.get("agent", ""))
        message = str(params.get("message", "")).strip()
        chain = peer_chain.get() or (caller,)
        reason = refusal(self._agents.ids(), chain, caller, target, message, peer_request.get())
        if reason is not None:
            return _result(tool_call_id, reason, is_error=True)

        caller_name = self._name_of(caller)
        target_name = self._name_of(target)
        token = peer_chain.set((*chain, target))
        request_token = peer_request.set(message)
        try:
            session = await self._opener(target, peer_session_id(caller, target), getattr(context, "session_id", None))
            logger.info(f"[Team] {caller} 가 {target} 에게 요청: {message[:80]}")
            request = peer_request_text(caller_name, message)
            reply = await asyncio.wait_for(ask(session, request), PEER_TIMEOUT_SEC)
        except SessionBusy:
            busy = f"{target_name} 가 지금 같은 대화에서 다른 일을 하고 있다. 잠시 뒤 다시 묻는다"
            return _result(tool_call_id, busy, True)
        except TimeoutError:
            return _result(tool_call_id, f"{target_name} 가 {int(PEER_TIMEOUT_SEC)}초 안에 답하지 않았다", True)
        finally:
            peer_chain.reset(token)
            peer_request.reset(request_token)
        logger.info(f"[Team] {target} 가 {caller} 에게 답: {reply[:80]}")
        return _result(tool_call_id, f"[{target_name} 의 답]\n{reply or '(빈 답)'}")

    def _name_of(self, agent_id: str) -> str:
        profile = self._agents.get(agent_id)
        return profile.name if profile is not None else agent_id


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=ASK_AGENT_TOOL, content=[TextContent(text=text)], is_error=is_error
    )
