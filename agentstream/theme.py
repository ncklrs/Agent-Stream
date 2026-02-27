"""AgentStream theme - colors, icons, ASCII art, and event rendering."""

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
ACCENT = "#818cf8"              # Indigo (for UI chrome)

AGENT_COLORS: dict[Agent, tuple[str, str]] = {
    Agent.CLAUDE: (CLAUDE_PRIMARY, CLAUDE_DIM),
    Agent.CODEX: (CODEX_PRIMARY, CODEX_DIM),
    Agent.SYSTEM: (SYSTEM_PRIMARY, SYSTEM_DIM),
}

# Action-specific colors (override agent color for content)
ACTION_STYLE: dict[ActionType, str] = {
    ActionType.ERROR: "#ef4444",
    ActionType.THINKING: "#6b7280",
    ActionType.REASONING: "#6b7280",
    ActionType.TOOL_USE: "#fbbf24",
    ActionType.COMMAND: "#f97316",
    ActionType.FILE_CHANGE: "#22d3ee",
    ActionType.MCP_TOOL: "#c084fc",
    ActionType.WEB_SEARCH: "#60a5fa",
    ActionType.TURN_COMPLETE: "#34d399",
    ActionType.TURN_FAILED: "#ef4444",
    ActionType.MESSAGE_START: "",   # Use agent color
    ActionType.MESSAGE_STOP: "",
    ActionType.STREAM_START: "#64748b",
    ActionType.STREAM_END: "#64748b",
}

# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

ACTION_ICONS: dict[ActionType, str] = {
    ActionType.TEXT: ">>",
    ActionType.TEXT_DELTA: ">>",
    ActionType.THINKING: "<>",
    ActionType.REASONING: "<>",
    ActionType.TOOL_USE: "{}",
    ActionType.COMMAND: "$ ",
    ActionType.FILE_CHANGE: "+-",
    ActionType.ERROR: "!!",
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
    ActionType.PING: "..",
    ActionType.UNKNOWN: "  ",
}

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

    # Separator
    line.append(" | ", style="dim #3a3a5c")

    # Icon
    line.append(f"{icon}", style=f"bold {content_color}")

    # Agent label
    agent_label = event.agent.value.upper()
    line.append(f" {agent_label:6s}", style=f"bold {primary}")

    # Separator
    line.append(" | ", style="dim #3a3a5c")

    # Action type (short label)
    action_label = event.action.value
    line.append(f"{action_label:12s}", style=f"{dim}")

    # Separator
    line.append("  ", style="")

    # Content
    line.append(event.content, style=content_color)

    return line


def render_logo() -> list[Text]:
    """Render the ASCII logo and tagline as styled Text lines."""
    lines: list[Text] = []

    # Empty line above
    lines.append(Text(""))

    # Logo
    for logo_line in LOGO.split("\n"):
        t = Text(logo_line, style=f"bold {ACCENT}")
        t.pad(1)
        lines.append(t)

    # Tagline
    tagline = Text()
    tagline.append(f"{'':>16}", style="")
    tagline.append(TAGLINE, style=f"italic {CLAUDE_DIM}")
    lines.append(tagline)

    # Separator
    lines.append(Text(""))
    sep = Text(f" {'─' * 58} ", style=f"dim #3a3a5c")
    lines.append(sep)
    lines.append(Text(""))

    return lines
