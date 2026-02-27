"""AgentStream theme - colors, icons, ASCII art, rendering, and help content."""

from rich.text import Text

from agentstream.events import Agent, ActionType, AgentEvent

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

AGENT_COLORS: dict[Agent, tuple[str, str]] = {
    Agent.CLAUDE: (CLAUDE_PRIMARY, CLAUDE_DIM),
    Agent.CODEX: (CODEX_PRIMARY, CODEX_DIM),
    Agent.SYSTEM: (SYSTEM_PRIMARY, SYSTEM_DIM),
}

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
# Rendering
# ---------------------------------------------------------------------------


def render_event(event: AgentEvent) -> Text:
    """Render an AgentEvent as a styled Rich Text line."""
    primary, dim = AGENT_COLORS.get(event.agent, (SYSTEM_PRIMARY, SYSTEM_DIM))
    icon = ACTION_ICONS.get(event.action, "  ")
    content_color = ACTION_STYLE.get(event.action, "") or primary

    ts = event.timestamp.strftime("%H:%M:%S")
    line = Text()

    # Timestamp
    line.append(f" {ts} ", style=f"dim {SYSTEM_DIM}")
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

    # Content
    line.append(f" {event.content}", style=content_color)

    return line


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
[bold #818cf8]AgentStream[/] [dim]v1.0.0[/]

[bold]Keyboard[/]
[bold #818cf8]space[/]  [#94a3b8]Pause / Resume auto-scrolling[/]
[bold #818cf8]    s[/]  [#94a3b8]Toggle sidebar (stream list)[/]
[bold #818cf8]    1[/]  [#94a3b8]Toggle Claude events on/off[/]
[bold #818cf8]    2[/]  [#94a3b8]Toggle Codex events on/off[/]
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

[bold]Pipe examples[/]
[#a78bfa]claude -p "task" \\
  --output-format stream-json | agentstream[/]
[#4ade80]codex exec --json "task" | agentstream[/]

[dim]Click streams in sidebar to toggle visibility
Press [bold]?[/bold] or [bold]Esc[/bold] to close[/]"""
