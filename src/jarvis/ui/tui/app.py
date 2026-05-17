from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, RichLog, Static

from jarvis.agent_layer.types import (
    AgentEndEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    TurnStartEvent,
)
from jarvis.core.session import AgentSession


class ChatHistory(RichLog):
    DEFAULT_CSS = "ChatHistory { border: solid $primary; height: 1fr; margin: 1; }"

    def add_user(self, text: str) -> None:
        self.write(f"[bold cyan]You:[/bold cyan] {text}")

    def add_assistant(self, text: str) -> None:
        self.write(f"[bold green]Jarvis:[/bold green] {text}")

    def add_tool(self, name: str, is_error: bool = False) -> None:
        color = "red" if is_error else "yellow"
        self.write(f"[{color}]  ⚙ {name}[/{color}]")

    def add_status(self, text: str) -> None:
        self.write(f"[dim]{text}[/dim]")

    def add_error(self, text: str) -> None:
        self.write(f"[bold red]Error:[/bold red] {text}")


class StatusBar(Static):
    DEFAULT_CSS = "StatusBar { dock: bottom; height: 1; background: $primary; color: $text; }"

    def set_status(self, text: str) -> None:
        self.update(text)


class JarvisTUI(App):
    """Jarvis 터미널 UI — Textual 기반."""

    CSS = """
    Screen { layout: vertical; }
    Input { dock: bottom; margin: 0 1; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+k", "abort", "Abort", show=True),
    ]

    def __init__(self, session: AgentSession, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._stream_buffer = ""
        self._streaming_started = False
        self._last_rendered = ""

        session.subscribe(self._on_agent_event)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ChatHistory(id="chat", markup=True, highlight=True, wrap=True)
        yield Input(placeholder="Type your message... (Ctrl+C to quit, Ctrl+K to abort)", id="input")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.disabled = True

        chat = self.query_one("#chat", ChatHistory)
        chat.add_user(text)

        self._stream_buffer = ""

        asyncio.create_task(self._run_prompt(text))

    async def _run_prompt(self, text: str) -> None:
        input_widget = self.query_one("#input", Input)
        try:
            await self._session.prompt(text)
        except Exception as exc:
            chat = self.query_one("#chat", ChatHistory)
            chat.add_error(str(exc))
        finally:
            input_widget.disabled = False
            input_widget.focus()

    async def _on_agent_event(self, event: AgentEvent) -> None:
        chat = self.query_one("#chat", ChatHistory)

        if isinstance(event, AgentStartEvent):
            chat.add_status("⏳ Thinking...")

        elif isinstance(event, MessageUpdateEvent):
            self._stream_buffer += event.text_delta or ""
            self._stream_buffer += event.thinking_delta or ""

        elif isinstance(event, AgentEndEvent):
            if self._stream_buffer:
                chat.add_assistant(self._stream_buffer)
                self._stream_buffer = ""

        elif isinstance(event, ToolExecutionStartEvent):
            chat.add_tool(f"Running {event.tool_name}...")

        elif isinstance(event, ToolExecutionEndEvent):
            status = "error" if event.is_error else "done"
            chat.add_tool(f"{event.tool_name} [{status}]", event.is_error)

        elif isinstance(event, AgentErrorEvent):
            chat.add_error(event.message)

    def action_abort(self) -> None:
        self._session.abort()

    async def on_mount(self) -> None:
        chat = self.query_one("#chat", ChatHistory)
        chat.write("[bold]Jarvis ready.[/bold] Type a message to begin.")
        self.query_one("#input", Input).focus()


def main() -> None:
    from pathlib import Path

    from jarvis.config import get_settings
    from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
    from jarvis.agent_layer.memory.sqlite import SqliteMemory
    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.core.plugins.loader import PluginLoader
    from jarvis.core.policy.authenticator import NoAuthAuthenticator
    from jarvis.core.policy.pipeline import SecurityPipeline
    from jarvis.core.policy.policy import AllowAllPolicy
    from jarvis.core.policy.sandbox import DefaultSandbox
    from jarvis.core.policy.validator import DefaultInputValidator
    from jarvis.core.skills.registry import SkillRegistry
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.core.tools.builtin.bash import BashTool
    from jarvis.core.tools.builtin.read_file import ReadFileTool
    from jarvis.core.tools.loader import ToolLoader
    from jarvis.model_layer.types import ModelConfig

    settings = get_settings()

    model = ModelConfig(
        provider=settings.llm.provider,
        model=settings.llm.model,
        api_key=settings.llm.api_key.get_secret_value() if settings.llm.api_key else None,
        base_url=settings.llm.base_url,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
    )

    memory_chain = MemoryMiddlewareChain(
        stages=[SqliteMemory(db_path=settings.memory.sqlite_path)]
    )
    session_repo = JsonlSessionRepo(sessions_root=settings.session.sessions_dir)

    pipeline = SecurityPipeline(
        validator=DefaultInputValidator(max_length=settings.security.input_max_length),
        authenticator=NoAuthAuthenticator(),
        policy=AllowAllPolicy(),
        sandbox=DefaultSandbox(
            dangerous_patterns=settings.security.dangerous_commands,
            require_approval_for=settings.security.require_approval_for,
        ),
    )

    tool_registry = ToolRegistry()
    tool_registry.register(BashTool())
    tool_registry.register(ReadFileTool())

    skill_registry = SkillRegistry()
    plugin_runner = PluginRunner()

    async def _setup() -> None:
        await session_repo.create(session_id="default")

        tools_dir = Path(settings.plugin.tools_dir).expanduser()
        if tools_dir.exists():
            loader = ToolLoader(tool_registry)
            await loader.load_directory(str(tools_dir))

        skills_dir = Path(settings.plugin.skills_dir).expanduser()
        if skills_dir.exists():
            await skill_registry.load_directory(str(skills_dir))

        plugins_dir = Path(settings.plugin.plugins_dir).expanduser()
        if plugins_dir.exists():
            plugin_loader = PluginLoader(plugin_runner)
            await plugin_loader.load_directory(str(plugins_dir))

    asyncio.run(_setup())

    session = AgentSession(
        model=model,
        session_id="default",
        security_pipeline=pipeline,
        plugin_runner=plugin_runner,
        memory_chain=memory_chain,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        session_repo=session_repo,
    )

    app = JarvisTUI(session=session)
    app.run()


if __name__ == "__main__":
    main()
