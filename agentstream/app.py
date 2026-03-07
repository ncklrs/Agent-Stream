"""AgentStream TUI application built with Textual."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
import time
from collections import Counter, deque
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
    AIDER_PRIMARY, AIDER_DIM,
    BG_DARK, BG_PANEL, BG_BAR, AGENT_COLORS, HELP_CONTENT,
    session_color, ERROR_FLASH,
)
from agentstream.streams import demo_stream, stdin_stream, file_stream, exec_stream, watch_stream

# Max events buffered while paused (prevent unbounded memory growth)
_PAUSE_BUFFER_MAX = 50_000
# Max events stored for search/filter/detail/export
_MAX_STORED_EVENTS = 10_000


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    try:
        if platform.system() == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=3)
            return True
        elif platform.system() == "Linux":
            # Try xclip first, then xsel
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    subprocess.run(cmd, input=text.encode(), check=True, timeout=3)
                    return True
                except FileNotFoundError:
                    continue
            # Try wl-copy for Wayland
            try:
                subprocess.run(["wl-copy"], input=text.encode(), check=True, timeout=3)
                return True
            except FileNotFoundError:
                pass
        elif platform.system() == "Windows":
            subprocess.run(["clip"], input=text.encode(), check=True, timeout=3)
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------

_HISTORY_DIR = pathlib.Path.home() / ".agentstream" / "history"


def _history_path() -> pathlib.Path:
    """Return the path for today's history file, creating dirs as needed."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return _HISTORY_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def _save_event(event: AgentEvent) -> None:
    """Append a single event to today's history file (best-effort)."""
    try:
        record = {
            "timestamp": event.timestamp.isoformat(),
            "agent": event.agent.value,
            "action": event.action.value,
            "content": event.content,
            "session_id": event.session_id,
        }
        if event.metadata:
            record["metadata"] = {
                k: v for k, v in event.metadata.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            }
        with open(_history_path(), "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # Never crash on history write


async def replay_stream(path: str) -> "AsyncGenerator[AgentEvent, None]":
    """Replay events from a history JSONL file."""
    from agentstream.events import Agent, ActionType, AgentEvent

    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START, f"Replaying {path}")

    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = AgentEvent(
                        agent=Agent(data.get("agent", "system")),
                        action=ActionType(data.get("action", "unknown")),
                        content=data.get("content", ""),
                        timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
                        session_id=data.get("session_id", ""),
                        metadata=data.get("metadata"),
                    )
                    yield event
                    await asyncio.sleep(0.01)  # Small delay for visual effect
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"File not found: {path}")
    except Exception as e:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"Replay error: {e}")

    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_END, f"Replay complete: {path}")


# ---------------------------------------------------------------------------
# Session toggle widget (sidebar item)
# ---------------------------------------------------------------------------

def _format_duration(secs: int) -> str:
    """Format seconds as compact duration string."""
    if secs < 60:
        return f"{secs}s"
    minutes = secs // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins:02d}m"


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
    duration_secs = reactive(0)

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

        # Line 2: status + count + cost + duration
        t.append(f"{indent}  ", style="")
        # Status indicator
        _status_colors = {"active": "#34d399", "quiet": "#facc15", "ended": "#ef4444"}
        status_color = _status_colors.get(self.status_text, SYSTEM_DIM)
        t.append(f"{self.status_text:6s}", style=f"dim {status_color}")
        t.append(f" {self.event_count:>4}", style=f"dim {SYSTEM_DIM}")
        if self.session_cost > 0:
            t.append(f" ${self.session_cost:.3f}", style=f"dim {SYSTEM_DIM}")
        elif self.duration_secs > 0:
            dur = _format_duration(self.duration_secs)
            t.append(f" {dur}", style=f"dim {SYSTEM_DIM}")

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
    #sidebar-footer {{
        height: auto;
        max-height: 3;
        dock: bottom;
        padding: 0 1;
        background: {BG_BAR};
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static(" STREAMS", id="sidebar-header")
        yield ScrollableContainer(id="session-container")
        yield Static("", id="sidebar-footer")

    def update_footer(self, claude_cost: float, codex_cost: float, aider_cost: float, total_events: int) -> None:
        """Update sidebar footer with cost breakdown."""
        t = Text()
        t.append(f" {'─' * 24}\n", style=f"dim {SEPARATOR_COLOR}")
        if claude_cost > 0 or codex_cost > 0 or aider_cost > 0:
            t.append(f" CL ${claude_cost:.4f}", style=f"dim {CLAUDE_DIM}")
            t.append(f"  CX ${codex_cost:.4f}", style=f"dim {CODEX_DIM}")
            if aider_cost > 0:
                t.append(f"\n AI ${aider_cost:.4f}", style=f"dim {AIDER_DIM}")
            t.append("\n", style="")
        t.append(f" {total_events:,} events", style=f"dim {SYSTEM_DIM}")
        try:
            self.query_one("#sidebar-footer", Static).update(t)
        except Exception:
            pass

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
        status: str = "", cost: float = 0.0, duration: int = 0,
    ) -> None:
        for toggle in self.query(SessionToggle):
            if toggle.session_id == session_id:
                toggle.event_count = count
                if status:
                    toggle.status_text = status
                if cost > 0:
                    toggle.session_cost = cost
                if duration > 0:
                    toggle.duration_secs = duration
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
        Binding("y", "copy_event", "Copy"),
        Binding("b", "toggle_bookmark", "Bookmark"),
        Binding("n", "next_bookmark", "Next bookmark"),
    ]

    def __init__(
        self,
        events: list[AgentEvent],
        sessions: dict[str, SessionInfo],
        bookmarked: set | None = None,
        start_index: int = -1,
    ) -> None:
        super().__init__()
        self._events = events
        self._sessions = sessions
        self._bookmarked = bookmarked or set()
        self._index = start_index if start_index >= 0 else (len(events) - 1 if events else 0)

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
        is_bm = id(event) in self._bookmarked
        nav = Text()
        nav.append(f" Event {self._index + 1}/{len(self._events)} ", style=f"dim {SYSTEM_DIM}")
        if is_bm:
            nav.append("*", style=f"bold #fbbf24")
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

    def action_copy_event(self) -> None:
        """Copy current event content to clipboard."""
        if not self._events:
            return
        event = self._events[self._index]
        text = event.content
        if _copy_to_clipboard(text):
            self.notify("Copied to clipboard", timeout=2)
        else:
            self.notify("Clipboard unavailable - content in terminal", timeout=3)

    def action_toggle_bookmark(self) -> None:
        """Toggle bookmark on the current event."""
        if not self._events:
            return
        event = self._events[self._index]
        eid = id(event)
        if eid in self._bookmarked:
            self._bookmarked.discard(eid)
        else:
            self._bookmarked.add(eid)
        self._render_current()

    def action_next_bookmark(self) -> None:
        """Jump to the next bookmarked event."""
        if not self._bookmarked:
            self.notify("No bookmarks set (press b to bookmark)", timeout=2)
            return
        # Search forward from current index, wrapping around
        for offset in range(1, len(self._events) + 1):
            idx = (self._index + offset) % len(self._events)
            if id(self._events[idx]) in self._bookmarked:
                self._index = idx
                self._render_current()
                return


# ---------------------------------------------------------------------------
# Stats screen (modal overlay)
# ---------------------------------------------------------------------------

class StatsScreen(ModalScreen[None]):
    """Modal showing event statistics breakdown."""

    CSS = f"""
    StatsScreen {{
        align: center middle;
    }}
    #stats-dialog {{
        width: 60;
        height: auto;
        max-height: 85%;
        background: {BG_BAR};
        border: heavy {SEPARATOR_COLOR};
        padding: 1 2;
        overflow-y: auto;
    }}
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("i", "dismiss", "Close"),
    ]

    def __init__(self, events: deque, sessions: dict[str, SessionInfo]) -> None:
        super().__init__()
        self._events = events
        self._sessions = sessions

    def compose(self) -> ComposeResult:
        yield ScrollableContainer(
            Static("", id="stats-content"),
            id="stats-dialog",
        )

    def on_mount(self) -> None:
        t = Text()
        t.append("  Event Statistics\n\n", style=f"bold {ACCENT}")

        if not self._events:
            t.append("  No events recorded.\n", style=f"dim {SYSTEM_DIM}")
            self.query_one("#stats-content", Static).update(t)
            return

        # Action type breakdown
        action_counts: Counter = Counter()
        agent_counts: Counter = Counter()
        session_counts: Counter = Counter()
        first_ts = self._events[0].timestamp
        last_ts = self._events[-1].timestamp
        total = len(self._events)

        for event in self._events:
            action_counts[event.action.value] += 1
            agent_counts[event.agent.value] += 1
            if event.session_id:
                session_counts[event.session_id] += 1

        # Time span
        span = (last_ts - first_ts).total_seconds()
        t.append("  Time span:  ", style=f"bold {SYSTEM_DIM}")
        t.append(f"{first_ts.strftime('%H:%M:%S')} - {last_ts.strftime('%H:%M:%S')}", style=ACCENT)
        if span > 0:
            rate = total / span
            t.append(f" ({rate:.1f} events/sec)\n", style=f"dim {SYSTEM_DIM}")
        else:
            t.append("\n", style="")

        t.append(f"  Total:      {total:,} events\n\n", style=f"dim {SYSTEM_DIM}")

        # By agent
        t.append(f"  {'─' * 50}\n", style=f"dim {SEPARATOR_COLOR}")
        t.append("  By Agent\n", style=f"bold {ACCENT}")
        for agent, count in agent_counts.most_common():
            pct = count / total * 100
            color = CLAUDE_PRIMARY if agent == "claude" else (CODEX_PRIMARY if agent == "codex" else (AIDER_PRIMARY if agent == "aider" else SYSTEM_DIM))
            bar_len = int(pct / 100 * 30)
            t.append(f"  {agent:8s} ", style=f"bold {color}")
            t.append("█" * bar_len, style=color)
            t.append(f" {count:>5} ({pct:.0f}%)\n", style=f"dim {SYSTEM_DIM}")

        # By action type (top 12)
        t.append(f"\n  {'─' * 50}\n", style=f"dim {SEPARATOR_COLOR}")
        t.append("  By Action Type (top 12)\n", style=f"bold {ACCENT}")
        for action, count in action_counts.most_common(12):
            pct = count / total * 100
            bar_len = int(pct / 100 * 30)
            t.append(f"  {action:12s} ", style=f"dim {SYSTEM_DIM}")
            t.append("█" * max(1, bar_len), style=ACCENT)
            t.append(f" {count:>5} ({pct:.0f}%)\n", style=f"dim {SYSTEM_DIM}")

        # By session (top 8)
        if session_counts:
            t.append(f"\n  {'─' * 50}\n", style=f"dim {SEPARATOR_COLOR}")
            t.append("  By Session (top 8)\n", style=f"bold {ACCENT}")
            for sid, count in session_counts.most_common(8):
                name = sid[:12]
                if sid in self._sessions:
                    name = self._sessions[sid].display_name[:12]
                pct = count / total * 100
                t.append(f"  {name:14s} ", style=f"dim {SYSTEM_DIM}")
                t.append(f"{count:>5} ({pct:.0f}%)\n", style=f"dim {SYSTEM_DIM}")

        t.append(f"\n  [i/Esc] close\n", style=f"dim {SYSTEM_DIM}")
        self.query_one("#stats-content", Static).update(t)


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
    aider_count = reactive(0)
    show_claude = reactive(True)
    show_codex = reactive(True)
    show_aider = reactive(True)
    total_cost = reactive(0.0)
    buffered_count = reactive(0)
    error_count = reactive(0)
    error_flash_active = reactive(False)
    filter_mode = reactive(FilterMode.ALL)
    search_active = reactive(False)
    relative_time = reactive(False)
    scroll_position = reactive("")
    bookmark_count = reactive(0)

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
        if self.aider_count > 0 or not self.show_aider:
            bar.append(" ", style="")
            ai_style = f"bold {AIDER_PRIMARY}" if self.show_aider else f"dim {AIDER_DIM}"
            bar.append(f"AI:{self.aider_count}", style=ai_style)

        # Error count
        if self.error_count > 0:
            bar.append(f" !{self.error_count}", style="bold #ef4444")

        # Bookmark count
        if self.bookmark_count > 0:
            bar.append(f" *{self.bookmark_count}", style=f"bold #fbbf24")

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
        Binding("3", "toggle_aider", "Aider", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
        Binding("f", "cycle_filter", "Filter", show=False),
        Binding("slash", "open_search", "Search", show=False),
        Binding("d", "show_detail", "Detail", show=False),
        Binding("t", "toggle_timestamps", "Timestamps", show=False),
        Binding("e", "export_events", "Export", show=False),
        Binding("b", "toggle_bookmark", "Bookmark", show=False),
        Binding("n", "next_bookmark", "Next bookmark", show=False),
        Binding("i", "show_stats", "Stats", show=False),
    ]

    paused = reactive(False)
    event_count = reactive(0)
    show_claude = reactive(True)
    show_codex = reactive(True)
    show_aider = reactive(True)
    filter_mode = reactive(FilterMode.ALL)
    search_term = reactive("")
    relative_time = reactive(False)

    def __init__(
        self,
        sources: list[tuple[str, Any]] | None = None,
        max_content: int = 200,
        bell: bool = False,
        save_history: bool = True,
    ) -> None:
        super().__init__()
        self.sources = sources or [("demo", None)]
        self.max_content = max_content
        self._bell = bell
        self._save_history = save_history
        self._tasks: list[asyncio.Task] = []
        self._sessions: dict[str, SessionInfo] = {}
        self._claude_count = 0
        self._codex_count = 0
        self._aider_count = 0
        self._claude_cost = 0.0
        self._codex_cost = 0.0
        self._aider_cost = 0.0
        self._total_cost = 0.0
        self._error_count = 0
        self._last_action: ActionType | None = None
        self._pause_buffer: deque[AgentEvent] = deque(maxlen=_PAUSE_BUFFER_MAX)
        # Tool call pairing: maps session_id -> (tool_name, start_time)
        self._last_tool_per_session: dict[str, tuple[str, datetime]] = {}
        # Store events for search/filter/detail/export
        self._all_events: deque[AgentEvent] = deque(maxlen=_MAX_STORED_EVENTS)
        self._search_active = False
        self._error_flash_timer: Timer | None = None
        # Track last event time per session for idle detection
        self._session_last_event: dict[str, float] = {}
        # Track session start times for duration
        self._session_start_time: dict[str, float] = {}
        # Bookmarks (set of event object ids)
        self._bookmarked: set[int] = set()
        # Text delta coalescing: buffer rapid deltas
        self._delta_buffer: dict[str, list[str]] = {}  # session_id -> content parts
        self._delta_flush_timer: Timer | None = None
        # Compiled regex for search (None = plain text search)
        self._search_regex: re.Pattern | None = None

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

        # Scroll position tracking
        self.set_interval(0.5, self._check_scroll_position)

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
        elif source_type == "replay":
            self._consume(replay_stream(config))

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
        # Persist to history file
        if self._save_history and event.agent != Agent.SYSTEM:
            _save_event(event)

        # Text delta coalescing: buffer rapid text deltas and flush periodically
        if event.action == ActionType.TEXT_DELTA and event.session_id:
            sid = event.session_id
            if sid not in self._delta_buffer:
                self._delta_buffer[sid] = []
            self._delta_buffer[sid].append(event.content)
            # Schedule a flush if not already pending
            if self._delta_flush_timer is None:
                self._delta_flush_timer = self.set_timer(0.15, self._flush_delta_buffer)
            return

        # Store for search/filter/detail/export
        self._all_events.append(event)

        # Track per-agent counts (always, even when paused/filtered)
        if event.agent == Agent.CLAUDE:
            self._claude_count += 1
        elif event.agent == Agent.CODEX:
            self._codex_count += 1
        elif event.agent == Agent.AIDER:
            self._aider_count += 1

        # Track errors
        if event.action in (ActionType.ERROR, ActionType.TURN_FAILED):
            self._error_count += 1
            self._flash_error()
            if self._bell:
                self.bell()

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

        # Track cost from result/metadata (per-agent)
        if event.metadata and "total_cost_usd" in event.metadata:
            cost = event.metadata["total_cost_usd"]
            if cost:
                self._total_cost += cost
                if event.agent == Agent.CLAUDE:
                    self._claude_cost += cost
                elif event.agent == Agent.CODEX:
                    self._codex_cost += cost
                elif event.agent == Agent.AIDER:
                    self._aider_cost += cost

        # Tool call pairing: track tool_use starts, annotate tool_results
        self._pair_tool_events(event)

        # Track connection status (STREAM_END = disconnected)
        if event.action == ActionType.STREAM_END and event.session_id:
            if event.session_id in self._sessions:
                self._sessions[event.session_id].connected = False
                try:
                    self.query_one(Sidebar).update_session(
                        event.session_id,
                        self._sessions[event.session_id].event_count,
                        status="ended",
                    )
                except Exception:
                    pass

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
            bookmarked=id(event) in self._bookmarked,
        ))
        self._last_action = event.action
        self.event_count += 1

    def _flush_pause_buffer(self) -> None:
        """Write all buffered events to the log, respecting current filters."""
        while self._pause_buffer:
            event = self._pause_buffer.popleft()
            if self._should_display(event):
                self._write_event_to_log(event)

    def _flush_delta_buffer(self) -> None:
        """Coalesce buffered text deltas into single events."""
        self._delta_flush_timer = None
        for sid, parts in self._delta_buffer.items():
            if parts:
                merged = "".join(parts)
                # Find the agent from sessions
                agent = Agent.CLAUDE
                if sid in self._sessions:
                    agent = self._sessions[sid].agent
                coalesced = AgentEvent(
                    agent=agent, action=ActionType.TEXT_DELTA,
                    content=merged, session_id=sid,
                )
                self._all_events.append(coalesced)
                # Save to history
                if self._save_history:
                    _save_event(coalesced)
                # Track counts
                if agent == Agent.CLAUDE:
                    self._claude_count += 1
                elif agent == Agent.CODEX:
                    self._codex_count += 1
                elif agent == Agent.AIDER:
                    self._aider_count += 1
                # Register session if needed
                if sid and sid not in self._sessions:
                    self._register_session(coalesced)
                if sid in self._sessions:
                    self._sessions[sid].event_count += 1
                    self._session_last_event[sid] = time.time()
                # Display
                if not self.paused and self._should_display(coalesced):
                    self._write_event_to_log(coalesced)
                elif self.paused:
                    self._pause_buffer.append(coalesced)
        self._delta_buffer.clear()
        self._update_status()

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
        if event.agent == Agent.AIDER and not self.show_aider:
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

        # Search filter (supports regex with /pattern/ syntax)
        if self.search_term:
            searchable = (
                event.content
                + " " + event.action.value
                + " " + event.agent.value
            )
            if self._search_regex:
                if not self._search_regex.search(searchable):
                    return False
            else:
                if self.search_term.lower() not in searchable.lower():
                    return False

        return True

    @staticmethod
    def _extract_tool_name(content: str) -> str:
        """Extract tool name from TOOL_USE / COMMAND content."""
        if not content:
            return "tool"
        if content.startswith("Calling ") and len(content.split()) >= 2:
            return content.split()[1]
        return content.split()[0]

    def _pair_tool_events(self, event: AgentEvent) -> None:
        """Track tool_use starts and annotate tool_result events with elapsed time."""
        sid = event.session_id or ""

        if event.action in (ActionType.TOOL_USE, ActionType.COMMAND):
            tool_name = self._extract_tool_name(event.content)
            self._last_tool_per_session[sid] = (tool_name, event.timestamp)

        elif event.action == ActionType.TOOL_RESULT:
            prev = self._last_tool_per_session.pop(sid, None)
            if prev:
                tool_name, start_time = prev
                elapsed = (event.timestamp - start_time).total_seconds()
                content = event.content or ""
                if elapsed >= 0.1:
                    event.content = f"{tool_name} -> {content} ({elapsed:.1f}s)"
                else:
                    event.content = f"{tool_name} -> {content}"

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
        self._session_start_time[sid] = time.time()

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
            status.aider_count = self._aider_count
            status.show_claude = self.show_claude
            status.show_codex = self.show_codex
            status.show_aider = self.show_aider
            status.total_cost = self._total_cost
            status.buffered_count = len(self._pause_buffer)
            status.error_count = self._error_count
            status.filter_mode = self.filter_mode
            status.search_active = self._search_active
            status.relative_time = self.relative_time
            status.bookmark_count = len(self._bookmarked)
        except Exception:
            pass

        # Update sidebar cost footer
        try:
            self.query_one(Sidebar).update_footer(
                self._claude_cost, self._codex_cost, self._aider_cost,
                len(self._all_events),
            )
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
                duration = int(now - self._session_start_time.get(sid, now))
                if info.status != status or duration > 0:
                    info.status = status
                    try:
                        self.query_one(Sidebar).update_session(
                            sid, info.event_count, status=status,
                            cost=info.total_cost, duration=duration,
                        )
                    except Exception:
                        pass

    def _check_scroll_position(self) -> None:
        """Update scroll position indicator in status bar."""
        try:
            log = self.query_one("#stream-log", RichLog)
            status = self.query_one(StatusBar)
            if log.auto_scroll or log.max_scroll_y <= 0:
                status.scroll_position = ""
            else:
                pct = int(log.scroll_y / log.max_scroll_y * 100) if log.max_scroll_y > 0 else 100
                below = int(log.max_scroll_y - log.scroll_y)
                if below > 0:
                    status.scroll_position = f"↑{pct}% ({below} below)"
                else:
                    status.scroll_position = ""
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
        if message.session_id not in self._sessions:
            return

        sid = message.session_id
        visible_count = sum(1 for s in self._sessions.values() if s.visible)

        # Solo logic: if clicking the only visible session (to disable it),
        # re-enable all sessions instead
        if not message.visible and visible_count == 1 and self._sessions[sid].visible:
            for s in self._sessions.values():
                s.visible = True
            for toggle in self.query_one(Sidebar).query(SessionToggle):
                toggle.enabled = True
            return

        # Normal toggle
        self._sessions[sid].visible = message.visible

    # --- Search handling ---

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "search-input":
            self.search_term = event.value
            # Compile regex if /pattern/ syntax used
            self._search_regex = None
            if self.search_term.startswith("/") and self.search_term.endswith("/") and len(self.search_term) > 2:
                pattern = self.search_term[1:-1]
                try:
                    self._search_regex = re.compile(pattern, re.IGNORECASE)
                except re.error:
                    pass  # Invalid regex, fall back to plain text
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
        self._aider_count = 0
        self._total_cost = 0.0
        self._claude_cost = 0.0
        self._codex_cost = 0.0
        self._aider_cost = 0.0
        self._error_count = 0
        self._last_action = None
        self._pause_buffer.clear()
        self._all_events.clear()
        self._bookmarked.clear()
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

    def action_toggle_aider(self) -> None:
        self.show_aider = not self.show_aider
        for toggle in self.query_one(Sidebar).query(SessionToggle):
            if toggle.agent == Agent.AIDER:
                toggle.enabled = self.show_aider
                self._sessions[toggle.session_id].visible = self.show_aider
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
        visible = [e for e in self._all_events if self._should_display(e)]
        if visible:
            self.push_screen(EventDetailScreen(visible, self._sessions, self._bookmarked))

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

    def action_show_stats(self) -> None:
        """Show event statistics modal."""
        self.push_screen(StatsScreen(self._all_events, self._sessions))

    def action_toggle_bookmark(self) -> None:
        """Toggle bookmark on the most recent event."""
        if not self._all_events:
            return
        event = self._all_events[-1]
        eid = id(event)
        if eid in self._bookmarked:
            self._bookmarked.discard(eid)
            self.notify("Bookmark removed", timeout=1)
        else:
            self._bookmarked.add(eid)
            self.notify("Bookmarked *", timeout=1)
        self._update_status()

    def action_next_bookmark(self) -> None:
        """Open detail view at the next bookmarked event."""
        if not self._bookmarked:
            self.notify("No bookmarks set (press b to bookmark)", timeout=2)
            return
        visible = [e for e in self._all_events if self._should_display(e)]
        # Find first bookmarked event
        for idx, event in enumerate(visible):
            if id(event) in self._bookmarked:
                self.push_screen(
                    EventDetailScreen(visible, self._sessions, self._bookmarked, start_index=idx)
                )
                return

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
