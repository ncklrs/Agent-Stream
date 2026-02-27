"""AgentStream TUI application built with Textual."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import RichLog, Static
from rich.text import Text

from agentstream.events import Agent, ActionType, AgentEvent
from agentstream.theme import render_event, render_logo, ACCENT, SYSTEM_DIM
from agentstream.streams import demo_stream, stdin_stream, file_stream, exec_stream


# ---------------------------------------------------------------------------
# Status bar widget
# ---------------------------------------------------------------------------

class StatusBar(Static):
    """Bottom status bar showing stream state and controls."""

    paused = reactive(False)
    event_count = reactive(0)

    def render(self) -> Text:
        bar = Text()

        # Status badge
        if self.paused:
            bar.append("  PAUSED  ", style="bold white on #b91c1c")
        else:
            bar.append(" STREAMING ", style="bold white on #059669")

        bar.append("  ", style="")

        # Event count
        bar.append(f"Events: {self.event_count}", style=f"{SYSTEM_DIM}")

        bar.append("  │  ", style=f"dim #3a3a5c")

        # Keybindings
        bar.append("[space]", style=f"bold {ACCENT}")
        bar.append(" pause  " if not self.paused else " resume  ", style=f"{SYSTEM_DIM}")
        bar.append("[c]", style=f"bold {ACCENT}")
        bar.append(" clear  ", style=f"{SYSTEM_DIM}")
        bar.append("[q]", style=f"bold {ACCENT}")
        bar.append(" quit", style=f"{SYSTEM_DIM}")

        return bar


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class AgentStreamApp(App):
    """AgentStream - combined agent event stream viewer."""

    TITLE = "AgentStream"
    CSS = """
    Screen {
        background: #0f0f17;
    }

    #stream-log {
        background: #0f0f17;
        scrollbar-color: #4a4a6a;
        scrollbar-color-hover: #6a6a8a;
        scrollbar-background: #1a1a2e;
        scrollbar-background-hover: #1a1a2e;
        border: none;
        padding: 0 0;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        background: #1a1a2e;
        color: #94a3b8;
        padding: 0 0;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_pause", "Pause/Resume", show=False),
        Binding("c", "clear_log", "Clear", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    paused = reactive(False)
    event_count = reactive(0)

    def __init__(self, sources: list[tuple[str, Any]] | None = None):
        super().__init__()
        self.sources = sources or [("demo", None)]
        self._tasks: list[asyncio.Task] = []

    def compose(self) -> ComposeResult:
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
        """Start stream consumers when the app mounts."""
        log = self.query_one("#stream-log", RichLog)

        # Write ASCII art header
        for line in render_logo():
            log.write(line)

        # Start all configured stream sources
        for source_type, config in self.sources:
            self._start_source(source_type, config)

    def _start_source(self, source_type: str, config: Any) -> None:
        """Launch a background worker for a stream source."""
        if source_type == "demo":
            self._consume(demo_stream())
        elif source_type == "stdin":
            self._consume(stdin_stream(config or "auto"))
        elif source_type == "file":
            self._consume(file_stream(config["agent"], config["path"]))
        elif source_type == "exec":
            self._consume(exec_stream(config["agent"], config["cmd"]))

    def _consume(self, stream) -> None:
        """Start consuming an async generator stream."""
        task = asyncio.ensure_future(self._consume_loop(stream))
        self._tasks.append(task)

    async def _consume_loop(self, stream) -> None:
        """Read events from a stream and display them."""
        try:
            async for event in stream:
                self._add_event(event)
        except asyncio.CancelledError:
            return
        except Exception as e:
            self._add_event(AgentEvent(
                agent=Agent.SYSTEM,
                action=ActionType.ERROR,
                content=f"Stream error: {e}",
            ))

    def _add_event(self, event: AgentEvent) -> None:
        """Add an event to the stream log."""
        log = self.query_one("#stream-log", RichLog)
        log.write(render_event(event))
        self.event_count += 1
        self.query_one(StatusBar).event_count = self.event_count

    # --- Actions ---

    def action_toggle_pause(self) -> None:
        """Toggle pause/resume."""
        self.paused = not self.paused
        log = self.query_one("#stream-log", RichLog)
        log.auto_scroll = not self.paused
        self.query_one(StatusBar).paused = self.paused

        if not self.paused:
            log.scroll_end(animate=False)

    def action_clear_log(self) -> None:
        """Clear the stream log."""
        log = self.query_one("#stream-log", RichLog)
        log.clear()
        self.event_count = 0
        self.query_one(StatusBar).event_count = 0

        # Re-write the header
        for line in render_logo():
            log.write(line)

    async def on_unmount(self) -> None:
        """Cancel background tasks on exit."""
        for task in self._tasks:
            task.cancel()
