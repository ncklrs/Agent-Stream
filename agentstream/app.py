"""AgentStream TUI application built with Textual."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static
from rich.text import Text

from agentstream.events import Agent, ActionType, AgentEvent, SessionInfo
from agentstream.theme import (
    render_event, render_logo, render_separator, SEPARATOR_ACTIONS,
    ACCENT, SYSTEM_DIM, SEPARATOR_COLOR,
    CLAUDE_PRIMARY, CLAUDE_DIM, CODEX_PRIMARY, CODEX_DIM,
    BG_DARK, BG_PANEL, BG_BAR, AGENT_COLORS, HELP_CONTENT,
    session_color,
)
from agentstream.streams import demo_stream, stdin_stream, file_stream, exec_stream, watch_stream

# Max events buffered while paused (prevent unbounded memory growth)
_PAUSE_BUFFER_MAX = 50_000


# ---------------------------------------------------------------------------
# Session toggle widget (sidebar item)
# ---------------------------------------------------------------------------

class SessionToggled(Message):
    """Posted when a session's visibility is toggled via sidebar click."""
    def __init__(self, session_id: str, visible: bool) -> None:
        super().__init__()
        self.session_id = session_id
        self.visible = visible


class SessionToggle(Static):
    """Clickable session entry in the sidebar."""

    DEFAULT_CSS = """
    SessionToggle {
        height: 2;
        padding: 0 1;
    }
    SessionToggle:hover {
        background: #1e1e30;
    }
    """

    enabled = reactive(True)
    event_count = reactive(0)

    def __init__(
        self,
        session_id: str,
        agent: Agent,
        display_name: str,
        color: str = "",
        color_dim: str = "",
    ) -> None:
        super().__init__("")
        self.session_id = session_id
        self.agent = agent
        self.display_name = display_name
        self._color = color
        self._color_dim = color_dim

    def render(self) -> Text:
        if self._color:
            primary, dim = self._color, self._color_dim
        else:
            primary, dim = AGENT_COLORS.get(self.agent, (SYSTEM_DIM, SYSTEM_DIM))
        icon = "●" if self.enabled else "○"
        style = f"bold {primary}" if self.enabled else f"dim {dim}"

        t = Text()
        t.append(f" {icon} ", style=style)
        t.append(f"{self.agent.value.upper()[:3]} ", style=style)
        t.append(self.display_name[:10], style=f"dim {dim}")
        t.append(f"  {self.event_count}", style=f"dim {SYSTEM_DIM}")
        return t

    def on_click(self) -> None:
        self.enabled = not self.enabled
        self.post_message(SessionToggled(self.session_id, self.enabled))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

class Sidebar(Vertical):
    """Sidebar showing all detected streams/sessions."""

    DEFAULT_CSS = f"""
    Sidebar {{
        width: 24;
        background: {BG_PANEL};
        border-right: solid {SEPARATOR_COLOR};
    }}
    Sidebar.-hidden {{
        display: none;
    }}
    #sidebar-header {{
        height: 1;
        background: {BG_BAR};
        color: {ACCENT};
        text-style: bold;
        padding: 0 1;
    }}
    #session-container {{
        height: 1fr;
        overflow-y: auto;
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static(" STREAMS", id="sidebar-header")
        yield ScrollableContainer(id="session-container")

    def add_session(
        self, session_id: str, agent: Agent, display_name: str,
        color: str = "", color_dim: str = "",
    ) -> None:
        container = self.query_one("#session-container")
        toggle = SessionToggle(session_id, agent, display_name, color, color_dim)
        container.mount(toggle)

    def update_session(self, session_id: str, count: int) -> None:
        for toggle in self.query(SessionToggle):
            if toggle.session_id == session_id:
                toggle.event_count = count
                return


# ---------------------------------------------------------------------------
# Help screen (modal overlay)
# ---------------------------------------------------------------------------

class HelpScreen(ModalScreen[None]):
    """Modal help overlay."""

    CSS = f"""
    HelpScreen {{
        align: center middle;
    }}
    #help-dialog {{
        width: 58;
        height: auto;
        max-height: 85%;
        background: {BG_BAR};
        border: heavy {SEPARATOR_COLOR};
        padding: 1 2;
    }}
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(HELP_CONTENT, id="help-dialog", markup=True)


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------

class StatusBar(Static):
    """Bottom status bar showing stream state and controls."""

    paused = reactive(False)
    event_count = reactive(0)
    claude_count = reactive(0)
    codex_count = reactive(0)
    show_claude = reactive(True)
    show_codex = reactive(True)
    total_cost = reactive(0.0)
    buffered_count = reactive(0)

    def render(self) -> Text:
        bar = Text()

        # Status badge
        if self.paused:
            bar.append("  PAUSED  ", style="bold white on #b91c1c")
            if self.buffered_count > 0:
                bar.append(f" +{self.buffered_count}", style="bold #fbbf24")
        else:
            bar.append(" STREAMING ", style="bold white on #059669")

        bar.append(" ", style="")

        # Per-agent counts
        cl_style = f"bold {CLAUDE_PRIMARY}" if self.show_claude else f"dim {CLAUDE_DIM}"
        bar.append(f"CL:{self.claude_count}", style=cl_style)
        bar.append(" ", style="")
        cx_style = f"bold {CODEX_PRIMARY}" if self.show_codex else f"dim {CODEX_DIM}"
        bar.append(f"CX:{self.codex_count}", style=cx_style)

        # Cost (if tracked)
        if self.total_cost > 0:
            bar.append(f" ${self.total_cost:.4f}", style=f"dim {SYSTEM_DIM}")

        bar.append(" | ", style=f"dim {SEPARATOR_COLOR}")

        # Key hints
        bar.append("[spc]", style=f"bold {ACCENT}")
        bar.append("pause ", style=f"dim {SYSTEM_DIM}")
        bar.append("[s]", style=f"bold {ACCENT}")
        bar.append("side ", style=f"dim {SYSTEM_DIM}")
        bar.append("[1]", style=f"bold {ACCENT}")
        bar.append("[2]", style=f"bold {ACCENT}")
        bar.append("filter ", style=f"dim {SYSTEM_DIM}")
        bar.append("[?]", style=f"bold {ACCENT}")
        bar.append("help ", style=f"dim {SYSTEM_DIM}")
        bar.append("[q]", style=f"bold {ACCENT}")
        bar.append("quit", style=f"dim {SYSTEM_DIM}")

        return bar


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class AgentStreamApp(App):
    """AgentStream - combined agent event stream viewer."""

    TITLE = "AgentStream"

    CSS = f"""
    Screen {{
        background: {BG_DARK};
    }}

    #main-container {{
        height: 1fr;
    }}

    #stream-log {{
        background: {BG_DARK};
        scrollbar-color: #4a4a6a;
        scrollbar-color-hover: #6a6a8a;
        scrollbar-background: #1a1a2e;
        scrollbar-background-hover: #1a1a2e;
        border: none;
        padding: 0 0;
    }}

    StatusBar {{
        dock: bottom;
        height: 1;
        background: {BG_BAR};
        color: #94a3b8;
        padding: 0 0;
    }}
    """

    BINDINGS = [
        Binding("space", "toggle_pause", "Pause/Resume", show=False),
        Binding("c", "clear_log", "Clear", show=False),
        Binding("q", "quit", "Quit", show=False),
        Binding("s", "toggle_sidebar", "Sidebar", show=False),
        Binding("1", "toggle_claude", "Claude", show=False),
        Binding("2", "toggle_codex", "Codex", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
    ]

    paused = reactive(False)
    event_count = reactive(0)
    show_claude = reactive(True)
    show_codex = reactive(True)

    def __init__(self, sources: list[tuple[str, Any]] | None = None) -> None:
        super().__init__()
        self.sources = sources or [("demo", None)]
        self._tasks: list[asyncio.Task] = []
        self._sessions: dict[str, SessionInfo] = {}
        self._claude_count = 0
        self._codex_count = 0
        self._total_cost = 0.0
        self._last_action: ActionType | None = None
        self._pause_buffer: deque[AgentEvent] = deque(maxlen=_PAUSE_BUFFER_MAX)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            yield Sidebar()
            yield RichLog(
                id="stream-log",
                highlight=False,
                markup=False,
                auto_scroll=True,
                wrap=True,
                max_lines=10_000,
            )
        yield StatusBar()

    def on_mount(self) -> None:
        log = self.query_one("#stream-log", RichLog)
        for line in render_logo():
            log.write(line)

        # Start with sidebar hidden by default
        self.query_one(Sidebar).add_class("-hidden")

        # Start all configured stream sources
        for source_type, config in self.sources:
            self._start_source(source_type, config)

    def _start_source(self, source_type: str, config: Any) -> None:
        if source_type == "demo":
            self._consume(demo_stream())
        elif source_type == "watch":
            self._consume(watch_stream())
        elif source_type == "stdin":
            self._consume(stdin_stream(config or "auto"))
        elif source_type == "file":
            self._consume(file_stream(config["agent"], config["path"]))
        elif source_type == "exec":
            self._consume(exec_stream(config["agent"], config["cmd"]))

    def _consume(self, stream) -> None:
        task = asyncio.ensure_future(self._consume_loop(stream))
        self._tasks.append(task)

    async def _consume_loop(self, stream) -> None:
        try:
            async for event in stream:
                self._add_event(event)
        except asyncio.CancelledError:
            return
        except Exception as e:
            self._add_event(AgentEvent(
                agent=Agent.SYSTEM, action=ActionType.ERROR,
                content=f"Stream error: {e}",
            ))

    # --- Event handling ---

    def _add_event(self, event: AgentEvent) -> None:
        # Track per-agent counts (always, even when paused/filtered)
        if event.agent == Agent.CLAUDE:
            self._claude_count += 1
        elif event.agent == Agent.CODEX:
            self._codex_count += 1

        # Register new session if we see a new session_id
        if event.session_id and event.session_id not in self._sessions:
            self._register_session(event)

        # Update session event count
        if event.session_id and event.session_id in self._sessions:
            info = self._sessions[event.session_id]
            info.event_count += 1
            try:
                self.query_one(Sidebar).update_session(event.session_id, info.event_count)
            except Exception:
                pass

        # Track cost from result/metadata
        if event.metadata and "total_cost_usd" in event.metadata:
            cost = event.metadata["total_cost_usd"]
            if cost:
                self._total_cost += cost

        # When paused, buffer events instead of writing to the log.
        # This prevents new writes from evicting lines the user is reading.
        if self.paused:
            self._pause_buffer.append(event)
            self._update_status()
            return

        # Check visibility filters
        if not self._should_display(event):
            self._update_status()
            return

        self._write_event_to_log(event)
        self._update_status()

    def _write_event_to_log(self, event: AgentEvent) -> None:
        """Render and write a single event to the RichLog."""
        log = self.query_one("#stream-log", RichLog)

        # Insert separator before major events
        if event.action in SEPARATOR_ACTIONS and self._last_action not in (None, ActionType.STREAM_START):
            log.write(render_separator())

        # Look up per-session colors (if the session is registered)
        colors = None
        if event.session_id and event.session_id in self._sessions:
            info = self._sessions[event.session_id]
            if info.color:
                colors = (info.color, info.color_dim)

        log.write(render_event(event, colors=colors))
        self._last_action = event.action
        self.event_count += 1

    def _flush_pause_buffer(self) -> None:
        """Write all buffered events to the log, respecting current filters."""
        while self._pause_buffer:
            event = self._pause_buffer.popleft()
            if self._should_display(event):
                self._write_event_to_log(event)

    def _should_display(self, event: AgentEvent) -> bool:
        """Check if event should be displayed based on current filters."""
        # System events always shown
        if event.agent == Agent.SYSTEM:
            return True

        # Agent-level filter
        if event.agent == Agent.CLAUDE and not self.show_claude:
            return False
        if event.agent == Agent.CODEX and not self.show_codex:
            return False

        # Session-level filter (sidebar toggles)
        if event.session_id and event.session_id in self._sessions:
            if not self._sessions[event.session_id].visible:
                return False

        return True

    def _register_session(self, event: AgentEvent) -> None:
        """Register a new session in the sidebar."""
        sid = event.session_id
        agent = event.agent

        # Generate display name
        if sid.startswith("demo-"):
            name = "Demo"
        else:
            name = sid[:8]

        # Assign a deterministic per-session color
        primary, dim = session_color(sid)

        info = SessionInfo(
            session_id=sid,
            agent=agent,
            display_name=name,
            color=primary,
            color_dim=dim,
        )
        self._sessions[sid] = info

        try:
            sidebar = self.query_one(Sidebar)
            sidebar.add_session(sid, agent, name, primary, dim)
        except Exception:
            pass

    def _update_status(self) -> None:
        """Push current state to the status bar."""
        try:
            status = self.query_one(StatusBar)
            status.event_count = self.event_count
            status.claude_count = self._claude_count
            status.codex_count = self._codex_count
            status.show_claude = self.show_claude
            status.show_codex = self.show_codex
            status.total_cost = self._total_cost
            status.buffered_count = len(self._pause_buffer)
        except Exception:
            pass

    # --- Session visibility (from sidebar clicks) ---

    def on_session_toggled(self, message: SessionToggled) -> None:
        if message.session_id in self._sessions:
            self._sessions[message.session_id].visible = message.visible

    # --- Actions ---

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        log = self.query_one("#stream-log", RichLog)
        log.auto_scroll = not self.paused
        self.query_one(StatusBar).paused = self.paused
        if not self.paused:
            self._flush_pause_buffer()
            log.scroll_end(animate=False)

    def action_clear_log(self) -> None:
        log = self.query_one("#stream-log", RichLog)
        log.clear()
        self.event_count = 0
        self._claude_count = 0
        self._codex_count = 0
        self._total_cost = 0.0
        self._last_action = None
        self._pause_buffer.clear()
        for line in render_logo():
            log.write(line)
        self._update_status()

    def action_toggle_sidebar(self) -> None:
        self.query_one(Sidebar).toggle_class("-hidden")

    def action_toggle_claude(self) -> None:
        self.show_claude = not self.show_claude
        # Also update all Claude session toggles in sidebar
        for toggle in self.query_one(Sidebar).query(SessionToggle):
            if toggle.agent == Agent.CLAUDE:
                toggle.enabled = self.show_claude
                self._sessions[toggle.session_id].visible = self.show_claude
        self._update_status()

    def action_toggle_codex(self) -> None:
        self.show_codex = not self.show_codex
        for toggle in self.query_one(Sidebar).query(SessionToggle):
            if toggle.agent == Agent.CODEX:
                toggle.enabled = self.show_codex
                self._sessions[toggle.session_id].visible = self.show_codex
        self._update_status()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    async def on_unmount(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
