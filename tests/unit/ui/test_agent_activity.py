"""AgentActivity: 세션의 시작과 끝으로 일하는 에이전트를 세고, 바뀔 때만 알린다."""

from jarvis.ui.web.agent_activity import AgentActivity


class _Session:
    def __init__(self):
        self.listeners = []

    def subscribe(self, fn):
        self.listeners.append(fn)
        return lambda: None

    async def emit(self, kind):
        for fn in self.listeners:
            await fn(type("E", (), {"type": kind})())


def test_mark_counts_agent_once_and_is_idempotent():
    activity = AgentActivity(broadcast=None)
    assert activity.mark("default", "main", True) is True
    assert activity.mark("default", "main", True) is False
    assert activity.mark("peer-karen-main", "main", True) is False  # 같은 에이전트의 다른 세션
    assert activity.mark("peer-main-karen", "karen", True) is True
    assert activity.active() == ["main", "karen"]
    assert activity.mark("default", "main", False) is False  # main 의 다른 세션이 아직 돈다
    assert activity.mark("peer-karen-main", "main", False) is True
    assert activity.active() == ["karen"]


async def test_watch_broadcasts_only_changes():
    sent = []

    async def broadcast(payload):
        sent.append(payload["active"])

    activity = AgentActivity(broadcast)
    main, karen = _Session(), _Session()
    activity.watch("default", "main", main)
    activity.watch("peer-main-karen", "karen", karen)

    await main.emit("agent_start")
    await karen.emit("agent_start")
    await karen.emit("message_update")
    await karen.emit("agent_end")
    await main.emit("agent_end")
    assert sent == [["main"], ["main", "karen"], ["main"], []]
