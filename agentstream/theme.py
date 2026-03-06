"""AgentStream theme - colors, icons, ASCII art, rendering, and help content."""

from datetime import datetime, timedelta

from rich.text import Text

from agentstream.events import Agent, ActionType, AgentEvent, FilterMode

# ---------------------------------------------------------------------------
# ASCII art
# ---------------------------------------------------------------------------

LOGO = """\
   ▄▀█ █▀▀ █▀▀ █▄░█ ▀█▀   █▀ ▀█▀ █▀█ █▀▀ ▄▀█ █▀▄▀█
   █▀█ █▄█ ██▄ █░▀█ ░█░   ▄█ ░█░ █▀▄ ██▄ █▀█ █░▀░█"""

TAGLINE = "your agents streaming by @ncklrs"

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

CLAUDE_PRIMARY = "#a78bfa"      # Violet
CLAUDE_DIM = "#7c6bc4"
CODEX_PRIMARY = "#4ade80"       # Green
CODEX_DIM = "#34a65d"
SYSTEM_PRIMARY = "#64748b"      # Slate
SYSTEM_DIM = "#475569"
ACCENT = "#818cf8"              # Indigo (UI chrome)
SEPARATOR_COLOR = "#2a2a3c"
BG_DARK = "#0f0f17"
BG_PANEL = "#13131f"
BG_BAR = "#1a1a2e"
ERROR_FLASH = "#b91c1c"         # Red flash for errors
SEARCH_HIGHLIGHT = "#fbbf24"    # Yellow for search matches

AGENT_COLORS: dict[Agent, tuple[str, str]] = {
    Agent.CLAUDE: (CLAUDE_PRIMARY, CLAUDE_DIM),
    Agent.CODEX: (CODEX_PRIMARY, CODEX_DIM),
    Agent.SYSTEM: (SYSTEM_PRIMARY, SYSTEM_DIM),
}

# Per-session color palette — 8 visually distinct pairs for dark backgrounds
SESSION_PALETTE: list[tuple[str, str]] = [
    ("#f472b6", "#db2777"),  # Pink
    ("#fb923c", "#ea580c"),  # Orange
    ("#facc15", "#ca8a04"),  # Yellow
    ("#34d399", "#059669"),  # Emerald
    ("#22d3ee", "#0891b2"),  # Cyan
    ("#818cf8", "#6366f1"),  # Indigo
    ("#c084fc", "#9333ea"),  # Purple
    ("#fb7185", "#e11d48"),  # Rose
]


def session_color(session_id: str) -> tuple[str, str]:
    """Deterministic color for a session — hash the ID into the palette."""
    idx = hash(session_id) % len(SESSION_PALETTE)
    return SESSION_PALETTE[idx]

# Action-specific content colors (empty = use agent color)
ACTION_STYLE: dict[ActionType, str] = {
    ActionType.ERROR: "#ef4444",
    ActionType.THINKING: "#6b7280",
    ActionType.REASONING: "#6b7280",
    ActionType.TOOL_USE: "#fbbf24",
    ActionType.TOOL_RESULT: "#a3a3a3",
    ActionType.COMMAND: "#f97316",
    ActionType.FILE_CHANGE: "#22d3ee",
    ActionType.MCP_TOOL: "#c084fc",
    ActionType.WEB_SEARCH: "#60a5fa",
    ActionType.TURN_COMPLETE: "#34d399",
    ActionType.TURN_FAILED: "#ef4444",
    ActionType.RESULT: "#34d399",
    ActionType.INIT: "",
    ActionType.COMPACT: "#64748b",
    ActionType.TASK_UPDATE: "#94a3b8",
    ActionType.USER_PROMPT: "#60a5fa",
    ActionType.STREAM_START: "#64748b",
    ActionType.STREAM_END: "#64748b",
}

# ---------------------------------------------------------------------------
# Icons (2-char, ASCII-safe)
# ---------------------------------------------------------------------------

ACTION_ICONS: dict[ActionType, str] = {
    ActionType.TEXT: ">>",
    ActionType.TEXT_DELTA: ">>",
    ActionType.THINKING: "<>",
    ActionType.REASONING: "<>",
    ActionType.TOOL_USE: "{}",
    ActionType.TOOL_RESULT: "<-",
    ActionType.COMMAND: "$ ",
    ActionType.FILE_CHANGE: "+-",
    ActionType.ERROR: "!!",
    ActionType.INIT: "->",
    ActionType.RESULT: "==",
    ActionType.MESSAGE_START: "->",
    ActionType.MESSAGE_STOP: "[]",
    ActionType.STREAM_START: "::",
    ActionType.STREAM_END: "::",
    ActionType.THREAD_START: "->",
    ActionType.TURN_START: "~~",
    ActionType.TURN_COMPLETE: "OK",
    ActionType.TURN_FAILED: "!!",
    ActionType.AGENT_MESSAGE: ">>",
    ActionType.MCP_TOOL: "{}",
    ActionType.WEB_SEARCH: "??",
    ActionType.COMPACT: "..",
    ActionType.TASK_UPDATE: ">>",
    ActionType.USER_PROMPT: "U>",
    ActionType.PING: "..",
    ActionType.UNKNOWN: "  ",
}

# Actions that trigger a separator line before them
SEPARATOR_ACTIONS = frozenset({
    ActionType.INIT,
    ActionType.MESSAGE_START,
    ActionType.THREAD_START,
    ActionType.TURN_START,
    ActionType.RESULT,
    ActionType.USER_PROMPT,
})

# ---------------------------------------------------------------------------
# Filter mode labels for the status bar
# ---------------------------------------------------------------------------

FILTER_MODE_LABELS: dict[FilterMode, tuple[str, str]] = {
    FilterMode.ALL: ("ALL", ACCENT),
    FilterMode.TOOLS: ("TOOLS", "#fbbf24"),
    FilterMode.ERRORS: ("ERRORS", "#ef4444"),
    FilterMode.TEXT: ("TEXT", CLAUDE_PRIMARY),
}

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _format_relative_time(ts: datetime) -> str:
    """Format a timestamp as relative time (e.g. '2s', '1m', '5m')."""
    delta = datetime.now() - ts
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "now"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h"


def render_event(
    event: AgentEvent,
    colors: tuple[str, str] | None = None,
    max_content: int = 200,
    relative_time: bool = False,
    search_term: str = "",
) -> Text:
    """Render an AgentEvent as a styled Rich Text line.

    *colors* overrides the agent label color with a per-session ``(primary, dim)`` pair.
    *max_content* controls content truncation length.
    *relative_time* shows "2s ago" style timestamps.
    *search_term* highlights matching text in content.
    """
    primary, dim = colors or AGENT_COLORS.get(event.agent, (SYSTEM_PRIMARY, SYSTEM_DIM))
    icon = ACTION_ICONS.get(event.action, "  ")
    content_color = ACTION_STYLE.get(event.action, "") or primary

    # Timestamp
    if relative_time:
        ts_str = f"{_format_relative_time(event.timestamp):>6s}"
    else:
        ts_str = event.timestamp.strftime("%H:%M:%S")

    line = Text()

    # Timestamp
    line.append(f" {ts_str} ", style=f"dim {SYSTEM_DIM}")
    line.append("|", style=f"dim {SEPARATOR_COLOR}")

    # Icon
    line.append(f" {icon}", style=f"bold {content_color}")

    # Agent label
    agent_label = event.agent.value.upper()
    line.append(f" {agent_label:6s}", style=f"bold {primary}")

    # Separator
    line.append(" |", style=f"dim {SEPARATOR_COLOR}")

    # Action type
    action_label = event.action.value
    line.append(f" {action_label:11s}", style=f"{dim}")

    # Content (truncated)
    content = event.content
    truncated = len(content) > max_content
    display_content = content[:max_content] + ("..." if truncated else "")

    if search_term and search_term.lower() in display_content.lower():
        # Highlight search matches
        lower_content = display_content.lower()
        lower_term = search_term.lower()
        pos = 0
        line.append(" ", style=content_color)
        while pos < len(display_content):
            idx = lower_content.find(lower_term, pos)
            if idx == -1:
                line.append(display_content[pos:], style=content_color)
                break
            line.append(display_content[pos:idx], style=content_color)
            line.append(
                display_content[idx:idx + len(search_term)],
                style=f"bold {SEARCH_HIGHLIGHT} on #3d2e00",
            )
            pos = idx + len(search_term)
    else:
        line.append(f" {display_content}", style=content_color)

    return line


def render_event_detail(event: AgentEvent, colors: tuple[str, str] | None = None) -> Text:
    """Render full event details for the detail modal."""
    primary, dim = colors or AGENT_COLORS.get(event.agent, (SYSTEM_PRIMARY, SYSTEM_DIM))
    content_color = ACTION_STYLE.get(event.action, "") or primary

    detail = Text()

    # Header
    detail.append("  Event Detail\n\n", style=f"bold {ACCENT}")

    # Timestamp
    detail.append("  Time:    ", style=f"bold {SYSTEM_DIM}")
    detail.append(f"{event.timestamp.strftime('%H:%M:%S.%f')[:-3]}\n", style=primary)

    # Agent
    detail.append("  Agent:   ", style=f"bold {SYSTEM_DIM}")
    detail.append(f"{event.agent.value.upper()}\n", style=f"bold {primary}")

    # Action
    detail.append("  Action:  ", style=f"bold {SYSTEM_DIM}")
    detail.append(f"{event.action.value}\n", style=dim)

    # Session
    if event.session_id:
        detail.append("  Session: ", style=f"bold {SYSTEM_DIM}")
        detail.append(f"{event.session_id}\n", style=f"dim {SYSTEM_DIM}")

    # Metadata
    if event.metadata:
        detail.append("  Meta:    ", style=f"bold {SYSTEM_DIM}")
        meta_items = []
        for k, v in event.metadata.items():
            if v is not None and v != "" and v != 0:
                meta_items.append(f"{k}={v}")
        detail.append(", ".join(meta_items) + "\n", style=f"dim {SYSTEM_DIM}")

    detail.append(f"\n  {'─' * 50}\n\n", style=f"dim {SEPARATOR_COLOR}")

    # Full content (no truncation)
    detail.append("  ", style="")
    detail.append(event.content or "(empty)", style=content_color)
    detail.append("\n", style="")

    return detail


def render_separator(label: str = "") -> Text:
    """Render a thin separator line for visual grouping."""
    if label:
        sep = f" {'─' * 4} {label} {'─' * max(1, 48 - len(label))} "
    else:
        sep = f" {'─' * 56} "
    return Text(sep, style=f"dim {SEPARATOR_COLOR}")


def render_logo() -> list[Text]:
    """Render the ASCII logo and tagline as styled Text lines."""
    lines: list[Text] = [Text("")]

    for logo_line in LOGO.split("\n"):
        t = Text(logo_line, style=f"bold {ACCENT}")
        t.pad(1)
        lines.append(t)

    tagline = Text()
    tagline.append(f"{'':>16}", style="")
    tagline.append(TAGLINE, style=f"italic {CLAUDE_DIM}")
    lines.append(tagline)

    lines.append(Text(""))
    lines.append(Text(f" {'─' * 58} ", style=f"dim {SEPARATOR_COLOR}"))
    lines.append(Text(""))

    return lines


# ---------------------------------------------------------------------------
# Help content
# ---------------------------------------------------------------------------

HELP_CONTENT = """\
[bold #818cf8]AgentStream[/] [dim]v1.1.0[/]

[bold]Keyboard[/]
[bold #818cf8]space[/]  [#94a3b8]Pause / Resume (buffers events)[/]
[bold #818cf8]    s[/]  [#94a3b8]Toggle sidebar (stream list)[/]
[bold #818cf8]    1[/]  [#94a3b8]Toggle Claude events on/off[/]
[bold #818cf8]    2[/]  [#94a3b8]Toggle Codex events on/off[/]
[bold #818cf8]    f[/]  [#94a3b8]Cycle filter: All → Tools → Errors → Text[/]
[bold #818cf8]    /[/]  [#94a3b8]Search events (Esc to clear)[/]
[bold #818cf8]    d[/]  [#94a3b8]Detail view (full event content)[/]
[bold #818cf8]    t[/]  [#94a3b8]Toggle timestamp mode (absolute/relative)[/]
[bold #818cf8]    e[/]  [#94a3b8]Export visible events to file[/]
[bold #818cf8]    c[/]  [#94a3b8]Clear the stream log[/]
[bold #818cf8]    ?[/]  [#94a3b8]Show / hide this help[/]
[bold #818cf8]    q[/]  [#94a3b8]Quit[/]

[bold]Usage[/]
[#94a3b8]agentstream[/]                           [dim]Watch mode[/]
[#94a3b8]agentstream --demo[/]                    [dim]Demo mode[/]
[#94a3b8]... | agentstream[/]                     [dim]Pipe (auto-detect)[/]
[#94a3b8]agentstream --stdin claude[/]            [dim]Pipe with hint[/]
[#94a3b8]agentstream --exec codex "cmd"[/]        [dim]Run subprocess[/]
[#94a3b8]agentstream --file codex path[/]         [dim]Watch log file[/]
[#94a3b8]agentstream --max-content 500[/]         [dim]Wider content[/]

[bold]Pipe examples[/]
[#a78bfa]claude -p "task" \\
  --output-format stream-json | agentstream[/]
[#4ade80]codex exec --json "task" | agentstream[/]

[dim]Click streams in sidebar to toggle visibility
Press [bold]?[/bold] or [bold]Esc[/bold] to close[/]"""
