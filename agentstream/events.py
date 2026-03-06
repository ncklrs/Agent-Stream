"""Event model for AgentStream."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Agent(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    SYSTEM = "system"


class ActionType(str, Enum):
    # Common
    TEXT = "text"
    TEXT_DELTA = "text_delta"
    ERROR = "error"

    # Lifecycle
    STREAM_START = "stream"
    STREAM_END = "stream_end"
    INIT = "init"
    RESULT = "result"

    # Claude
    MESSAGE_START = "msg_start"
    MESSAGE_STOP = "msg_stop"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    PING = "ping"
    COMPACT = "compact"
    TASK_UPDATE = "task"
    USER_PROMPT = "user_prompt"

    # Codex
    THREAD_START = "thread"
    TURN_START = "turn"
    TURN_COMPLETE = "turn_done"
    TURN_FAILED = "turn_fail"
    COMMAND = "command"
    FILE_CHANGE = "file_edit"
    REASONING = "reasoning"
    AGENT_MESSAGE = "message"
    MCP_TOOL = "mcp_tool"
    WEB_SEARCH = "search"

    # Meta
    UNKNOWN = "unknown"


class FilterMode(str, Enum):
    """Action-type filter modes for the event log."""
    ALL = "all"
    TOOLS = "tools"
    ERRORS = "errors"
    TEXT = "text"


# Which action types each filter mode passes through
FILTER_MODE_ACTIONS: dict[FilterMode, frozenset[ActionType]] = {
    FilterMode.ALL: frozenset(ActionType),
    FilterMode.TOOLS: frozenset({
        ActionType.TOOL_USE, ActionType.TOOL_RESULT, ActionType.COMMAND,
        ActionType.FILE_CHANGE, ActionType.MCP_TOOL, ActionType.WEB_SEARCH,
        ActionType.ERROR, ActionType.INIT, ActionType.RESULT,
        ActionType.STREAM_START, ActionType.STREAM_END,
    }),
    FilterMode.ERRORS: frozenset({
        ActionType.ERROR, ActionType.TURN_FAILED,
        ActionType.STREAM_START, ActionType.STREAM_END,
    }),
    FilterMode.TEXT: frozenset({
        ActionType.TEXT, ActionType.TEXT_DELTA, ActionType.AGENT_MESSAGE,
        ActionType.THINKING, ActionType.REASONING, ActionType.USER_PROMPT,
        ActionType.STREAM_START, ActionType.STREAM_END,
    }),
}


@dataclass(slots=True)
class AgentEvent:
    agent: Agent
    action: ActionType
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    session_id: str = ""
    metadata: Optional[dict] = field(default_factory=dict)


@dataclass
class SessionInfo:
    """Tracks a detected stream/session in the sidebar."""
    session_id: str
    agent: Agent
    display_name: str
    visible: bool = True
    event_count: int = 0
    status: str = "active"
    total_cost: float = 0.0
    color: str = ""
    color_dim: str = ""
