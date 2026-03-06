"""AgentStream TUI application built with Textual."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static, Input
from textual.timer import Timer
from rich.text import Text

from agentstream.events import (
    Agent, ActionType, AgentEvent, SessionInfo, FilterMode, FILTER_MODE_ACTIONS,
)
from agentstream.theme import (
    render_event, render_logo, render_separator, SEPARATOR_ACTIONS,
    render_event_detail, FILTER_MODE_LABELS,
    ACCENT, SYSTEM_DIM, SEPARATOR_COLOR,
    CLAUDE_PRIMARY, CLAUDE_DIM, CODEX_PRIMARY, CODEX_DIM,
    BG_DARK, BG_PANEL, BG_BAR, AGENT_COLORS, HELP_CONTENT,
    session_color, ERROR_FLASH,
)
from agentstream.streams import demo_stream, stdin_stream, file_stream, exec_stream, watch_stream

# Max events buffered while paused (prevent unbounded memory growth)
_PAUSE_BUFFER_MAX = 50_000
# Max events stored for search/filter/detail/export
_MAX_STORED_EVENTS = 10_000


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
        height: 3;
        padding: 0 1;
    }
    SessionToggle:hover {
        background: #1e1e30;
    }
    """

    enabled = reactive(True)
    event_count = reactive(0)
    status_text = reactive("active")
    session_cost = reactive(0.0)

    def __init__(
        self,
        session_id: str,
        agent: Agent,
        display_name: str,
        color: str = "",
        color_dim: str = "",
        is_subagent: bool = False,
    ) -> None:
        super().__init__("")
        self.session_id = session_id
        self.agent = agent
        self.display_name = display_name
        self._color = color
        self._color_dim = color_dim
        self.is_subagent = is_subagent

    def render(self) -> Text:
        if self._color:
            primary, dim = self._color, self._color_dim
        else:
            primary, dim = AGENT_COLORS.get(self.agent, (SYSTEM_DIM, SYSTEM_DIM))
        icon = "●" if self.enabled else "○"
        style = f"bold {primary}" if self.enabled else f"dim {dim}"

        t = Text()
        # Subagent indentation
        indent = " ↳ " if self.is_subagent else " "

        # Line 1: icon + agent + name
        t.append(f"{indent}{icon} ", style=style)
        t.append(f"{self.agent.value.upper()[:3]} ", style=style)
        t.append(self.display_name[:14], style=f"dim {dim}")
        t.append("\n", style="")

        # Line 2: status + count + cost
        t.append(f"{indent}  ", style="")
        # Status indicator
        status_color = "#34d399" if self.status_text == "active" else SYSTEM_DIM
        t.append(f"{self.status_text:6s}", style=f"dim {status_color}")
        t.append(f" {self.event_count:>4}", style=f"dim {SYSTEM_DIM}")
        if self.session_cost > 0:
            t.append(f" ${self.session_cost:.3f}", style=f"dim {SYSTEM_DIM}")

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
        width: 28;
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
        is_subagent: bool = False,
    ) -> None:
        container = self.query_one("#session-container")
        toggle = SessionToggle(
            session_id, agent, display_name, color, color_dim,
            is_subagent=is_subagent,
        )
        container.mount(toggle)

    def update_session(
        self, session_id: str, count: int,
        status: str = "", cost: float = 0.0,
    ) -> None:
        for toggle in self.query(SessionToggle):
            if toggle.session_id == session_id:
                toggle.event_count = count
                if status:
                    toggle.status_text = status
                if cost > 0:
                    toggle.session_cost = cost
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
# Event detail screen (modal overlay)
# ---------------------------------------------------------------------------

class EventDetailScreen(ModalScreen[None]):
    """Modal showing full event details with navigation."""

    CSS = f"""
    EventDetailScreen {{
        align: center middle;
    }}
    #detail-dialog {{
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 85%;
        background: {BG_BAR};
        border: heavy {SEPARATOR_COLOR};
        padding: 1 2;
        overflow-y: auto;
    }}
    #detail-nav {{
        height: 1;
        dock: bottom;
        background: {BG_PANEL};
        padding: 0 1;
    }}
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("d", "dismiss", "Close"),
        Binding("up,k", "prev_event", "Previous"),
        Binding("down,j", "next_event", "Next"),
    ]

    def __init__(self, events: list[AgentEvent], sessions: dict[str, SessionInfo]) -> None:
        super().__init__()
        self._events = events
        self._sessions = sessions
        self._index = len(events) - 1 if events else 0

    def compose(self) -> ComposeResult:
        yield ScrollableContainer(
            Static("", id="detail-content"),
            id="detail-dialog",
        )
        yield Static("", id="detail-nav")

    def on_mount(self) -> None:
        self._render_current()

    def _render_current(self) -> None:
        if not self._events:
            self.query_one("#detail-content", Static).update(
                Text("No events to display", style=f"dim {SYSTEM_DIM}")
            )
            return

        event = self._events[self._index]
        colors = None
        if event.session_id and event.session_id in self._sessions:
            info = self._sessions[event.session_id]
            if info.color:
                colors = (info.color, info.color_dim)

        self.query_one("#detail-content", Static).update(render_event_detail(event, colors))

        # Navigation hint
        nav = Text()
        nav.append(f" Event {self._index + 1}/{len(self._events)} ", style=f"dim {SYSTEM_DIM}")
        nav.append("  [↑/k]", style=f"bold {ACCENT}")
        nav.append("prev ", style=f"dim {SYSTEM_DIM}")
        nav.append("[↓/j]", style=f"bold {ACCENT}")
        nav.append("next ", style=f"dim {SYSTEM_DIM}")
        nav.append("[d/Esc]", style=f"bold {ACCENT}")
        nav.append("close", style=f"dim {SYSTEM_DIM}")
        self.query_one("#detail-nav", Static).update(nav)

    def action_prev_event(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._render_current()

    def action_next_event(self) -> None:
        if self._index < len(self._events) - 1:
            self._index += 1
            self._render_current()


# ---------------------------------------------------------------------------
# Search bar
# ---------------------------------------------------------------------------

class SearchBar(Horizontal):
    """Bottom search input bar."""

    DEFAULT_CSS = f"""
    SearchBar {{
        dock: bottom;
        height: 1;
        background: {BG_BAR};
        display: none;
    }}
    SearchBar.-visible {{
        display: block;
    }}
    #search-label {{
        width: 3;
        color: {ACCENT};
        text-style: bold;
        padding: 0 0 0 1;
    }}
    #search-input {{
        width: 1fr;
        background: {BG_DARK};
        color: #e2e8f0;
        border: none;
        height: 1;
        padding: 0;
    }}
    #search-count {{
        width: auto;
        min-width: 8;
        color: {SYSTEM_DIM};
        padding: 0 1 0 0;
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static(" /", id="search-label")
        yield Input(placeholder="search events...", id="search-input")
        yield Static("", id="search-count")


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
    error_count = reactive(0)
    error_flash_active = reactive(False)
    filter_mode = reactive(FilterMode.ALL)
    search_active = reactive(False)
    relative_time = reactive(False)
    scroll_position = reactive("")

    def render(self) -> Text:
        bar = Text()

        # Status badge
        if self.error_flash_active:
            bar.append("  ERROR!  ", style="bold white on #b91c1c")
        elif self.paused:
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

        # Error count
        if self.error_count > 0:
            bar.append(f" !{self.error_count}", style="bold #ef4444")

        # Cost (if tracked)
        if self.total_cost > 0:
            bar.append(f" ${self.total_cost:.4f}", style=f"dim {SYSTEM_DIM}")

        # Filter mode (if not ALL)
        if self.filter_mode != FilterMode.ALL:
            label, color = FILTER_MODE_LABELS[self.filter_mode]
            bar.append(f" [{label}]", style=f"bold {color}")

        # Relative time indicator
        if self.relative_time:
            bar.append(" ~t", style=f"dim {ACCENT}")

        # Scroll position
        if self.scroll_position:
            bar.append(f" {self.scroll_position}", style=f"dim {SYSTEM_DIM}")

        bar.append(" | ", style=f"dim {SEPARATOR_COLOR}")

        # Key hints
        bar.append("[/]", style=f"bold {ACCENT}")
        bar.append("find ", style=f"dim {SYSTEM_DIM}")
        bar.append("[f]", style=f"bold {ACCENT}")
        bar.append("filter ", style=f"dim {SYSTEM_DIM}")
        bar.append("[spc]", style=f"bold {ACCENT}")
        bar.append("pause ", style=f"dim {SYSTEM_DIM}")
        bar.append("[?]", style=f"bold {ACCENT}")
        bar.append("help", style=f"dim {SYSTEM_DIM}")

        return bar


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

_FILTER_CYCLE = [FilterMode.ALL, FilterMode.TOOLS, FilterMode.ERRORS, FilterMode.TEXT]


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
        Binding("f", "cycle_filter", "Filter", show=False),
        Binding("slash", "open_search", "Search", show=False),
        Binding("d", "show_detail", "Detail", show=False),
        Binding("t", "toggle_timestamps", "Timestamps", show=False),
        Binding("e", "export_events", "Export", show=False),
    ]

    paused = reactive(False)
    event_count = reactive(0)
    show_claude = reactive(True)
    show_codex = reactive(True)
    filter_mode = reactive(FilterMode.ALL)
    search_term = reactive("")
    relative_time = reactive(False)

    def __init__(
        self,
        sources: list[tuple[str, Any]] | None = None,
        max_content: int = 200,
    ) -> None:
        super().__init__()
        self.sources = sources or [("demo", None)]
        self.max_content = max_content
        self._tasks: list[asyncio.Task] = []
        self._sessions: dict[str, SessionInfo] = {}
        self._claude_count = 0
        self._codex_count = 0
        self._total_cost = 0.0
        self._error_count = 0
        self._last_action: ActionType | None = None
        self._pause_buffer: deque[AgentEvent] = deque(maxlen=_PAUSE_BUFFER_MAX)
        # Store events for search/filter/detail/export
        self._all_events: deque[AgentEvent] = deque(maxlen=_MAX_STORED_EVENTS)
        self._search_active = False
        self._error_flash_timer: Timer | None = None
        # Track last event time per session for idle detection
        self._session_last_event: dict[str, float] = {}

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
        yield SearchBar()
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

        # Periodic session idle check
        self.set_interval(10.0, self._check_session_idle)

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
        # Store for search/filter/detail/export
        self._all_events.append(event)

        # Track per-agent counts (always, even when paused/filtered)
        if event.agent == Agent.CLAUDE:
            self._claude_count += 1
        elif event.agent == Agent.CODEX:
            self._codex_count += 1

        # Track errors
        if event.action in (ActionType.ERROR, ActionType.TURN_FAILED):
            self._error_count += 1
            self._flash_error()

        # Register new session if we see a new session_id
        if event.session_id and event.session_id not in self._sessions:
            self._register_session(event)

        # Update session event count and timing
        if event.session_id and event.session_id in self._sessions:
            info = self._sessions[event.session_id]
            info.event_count += 1
            self._session_last_event[event.session_id] = time.time()

            # Track per-session cost
            if event.metadata and "total_cost_usd" in event.metadata:
                cost = event.metadata["total_cost_usd"]
                if cost:
                    info.total_cost += cost

            try:
                self.query_one(Sidebar).update_session(
                    event.session_id, info.event_count,
                    status="active",
                    cost=info.total_cost,
                )
            except Exception:
                pass

        # Track cost from result/metadata
        if event.metadata and "total_cost_usd" in event.metadata:
            cost = event.metadata["total_cost_usd"]
            if cost:
                self._total_cost += cost

        # When paused, buffer events instead of writing to the log.
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

        log.write(render_event(
            event, colors=colors,
            max_content=self.max_content,
            relative_time=self.relative_time,
            search_term=self.search_term,
        ))
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

        # Action type filter
        if self.filter_mode != FilterMode.ALL:
            allowed = FILTER_MODE_ACTIONS.get(self.filter_mode)
            if allowed and event.action not in allowed:
                return False

        # Search filter
        if self.search_term:
            term = self.search_term.lower()
            searchable = (
                event.content.lower()
                + " " + event.action.value.lower()
                + " " + event.agent.value.lower()
            )
            if term not in searchable:
                return False

        return True

    def _register_session(self, event: AgentEvent) -> None:
        """Register a new session in the sidebar."""
        sid = event.session_id
        agent = event.agent

        # Detect if this is a subagent from session ID or metadata
        is_subagent = "subagent" in sid.lower() or (
            event.metadata and "subagent" in str(event.metadata.get("project_name", "")).lower()
        )

        # Generate display name — prefer slug (session name) from Claude data
        if sid.startswith("demo-"):
            name = "Demo"
        elif event.metadata and event.metadata.get("slug"):
            slug = event.metadata["slug"]
            name = slug.rsplit("-", 1)[-1]
        elif event.metadata and event.metadata.get("project_name"):
            name = event.metadata["project_name"]
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
        self._session_last_event[sid] = time.time()

        try:
            sidebar = self.query_one(Sidebar)
            sidebar.add_session(sid, agent, name, primary, dim, is_subagent=is_subagent)
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
            status.error_count = self._error_count
            status.filter_mode = self.filter_mode
            status.search_active = self._search_active
            status.relative_time = self.relative_time
        except Exception:
            pass

    def _flash_error(self) -> None:
        """Flash the status bar on errors."""
        try:
            status = self.query_one(StatusBar)
            status.error_flash_active = True
            # Clear flash after 1 second
            if self._error_flash_timer:
                self._error_flash_timer.stop()
            self._error_flash_timer = self.set_timer(
                1.0, self._clear_error_flash,
            )
        except Exception:
            pass

    def _clear_error_flash(self) -> None:
        """Clear the error flash indicator."""
        try:
            self.query_one(StatusBar).error_flash_active = False
        except Exception:
            pass

    def _check_session_idle(self) -> None:
        """Update session status to idle if no events received recently."""
        now = time.time()
        for sid, last_time in self._session_last_event.items():
            if sid in self._sessions:
                elapsed = now - last_time
                if elapsed > 30:
                    status = "idle"
                elif elapsed > 10:
                    status = "quiet"
                else:
                    status = "active"
                info = self._sessions[sid]
                if info.status != status:
                    info.status = status
                    try:
                        self.query_one(Sidebar).update_session(
                            sid, info.event_count, status=status, cost=info.total_cost,
                        )
                    except Exception:
                        pass

    def _rebuild_log(self) -> None:
        """Rebuild the event log from stored events applying current filters."""
        log = self.query_one("#stream-log", RichLog)
        log.clear()
        self.event_count = 0
        self._last_action = None

        for line in render_logo():
            log.write(line)

        for event in self._all_events:
            if self._should_display(event):
                self._write_event_to_log(event)

    # --- Session visibility (from sidebar clicks) ---

    def on_session_toggled(self, message: SessionToggled) -> None:
        if message.session_id in self._sessions:
            self._sessions[message.session_id].visible = message.visible

    # --- Search handling ---

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "search-input":
            self.search_term = event.value
            self._rebuild_log()
            # Update match count
            if self.search_term:
                count = sum(
                    1 for e in self._all_events
                    if self._should_display(e)
                )
                try:
                    self.query_one("#search-count", Static).update(
                        Text(f" {count} ", style=f"dim {SYSTEM_DIM}")
                    )
                except Exception:
                    pass
            else:
                try:
                    self.query_one("#search-count", Static).update("")
                except Exception:
                    pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Close search on Enter."""
        if event.input.id == "search-input":
            self._dismiss_search()

    # --- Actions ---

    def action_toggle_pause(self) -> None:
        if self._search_active:
            return
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
        self._error_count = 0
        self._last_action = None
        self._pause_buffer.clear()
        self._all_events.clear()
        for sid in self._sessions:
            self._sessions[sid].event_count = 0
            self._sessions[sid].total_cost = 0.0
        for line in render_logo():
            log.write(line)
        self._update_status()

    def action_toggle_sidebar(self) -> None:
        self.query_one(Sidebar).toggle_class("-hidden")

    def action_toggle_claude(self) -> None:
        self.show_claude = not self.show_claude
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

    def action_cycle_filter(self) -> None:
        """Cycle through filter modes: ALL -> TOOLS -> ERRORS -> TEXT -> ALL."""
        if self._search_active:
            return
        idx = _FILTER_CYCLE.index(self.filter_mode)
        self.filter_mode = _FILTER_CYCLE[(idx + 1) % len(_FILTER_CYCLE)]
        self._rebuild_log()
        self._update_status()

    def action_open_search(self) -> None:
        """Show the search bar and focus the input."""
        self._search_active = True
        search_bar = self.query_one(SearchBar)
        search_bar.add_class("-visible")
        search_input = self.query_one("#search-input", Input)
        search_input.value = ""
        search_input.focus()

    def _dismiss_search(self) -> None:
        """Hide search bar and clear search."""
        self._search_active = False
        search_bar = self.query_one(SearchBar)
        search_bar.remove_class("-visible")
        # Keep search term active if user pressed Enter
        # Clear on Escape
        self._update_status()

    def action_show_detail(self) -> None:
        """Show event detail modal."""
        if not self._all_events:
            return
        # Show only visible events in the detail view
        visible = [e for e in self._all_events if self._should_display(e)]
        if visible:
            self.push_screen(EventDetailScreen(visible, self._sessions))

    def action_toggle_timestamps(self) -> None:
        """Toggle between absolute and relative timestamps."""
        self.relative_time = not self.relative_time
        self._rebuild_log()
        self._update_status()

    def action_export_events(self) -> None:
        """Export visible events to a JSONL file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"agentstream_export_{timestamp}.jsonl"
        filepath = os.path.join(os.getcwd(), filename)

        count = 0
        try:
            with open(filepath, "w") as f:
                for event in self._all_events:
                    if self._should_display(event):
                        record = {
                            "timestamp": event.timestamp.isoformat(),
                            "agent": event.agent.value,
                            "action": event.action.value,
                            "content": event.content,
                            "session_id": event.session_id,
                        }
                        if event.metadata:
                            record["metadata"] = event.metadata
                        f.write(json.dumps(record) + "\n")
                        count += 1

            self.notify(
                f"Exported {count} events to {filename}",
                title="Export",
                timeout=3,
            )
        except Exception as e:
            self.notify(
                f"Export failed: {e}",
                title="Export Error",
                severity="error",
                timeout=5,
            )

    def on_key(self, event) -> None:
        """Handle Escape in search mode."""
        if event.key == "escape" and self._search_active:
            self._search_active = False
            self.search_term = ""
            self.query_one(SearchBar).remove_class("-visible")
            self._rebuild_log()
            self._update_status()
            event.prevent_default()

    async def on_unmount(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
