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
    ERROR = "error"

    # Lifecycle
    STREAM_START = "stream_start"
    STREAM_END = "stream_end"

    # Claude
    MESSAGE_START = "msg_start"
    MESSAGE_STOP = "msg_stop"
    CONTENT_START = "content_start"
    CONTENT_STOP = "content_stop"
    TEXT_DELTA = "text"
    TOOL_USE = "tool_use"
    THINKING = "thinking"
    PING = "ping"

    # Codex
    THREAD_START = "thread_start"
    TURN_START = "turn_start"
    TURN_COMPLETE = "turn_done"
    TURN_FAILED = "turn_failed"
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    REASONING = "reasoning"
    AGENT_MESSAGE = "message"
    MCP_TOOL = "mcp_tool"
    WEB_SEARCH = "web_search"

    # Meta
    UNKNOWN = "unknown"


@dataclass(slots=True)
class AgentEvent:
    agent: Agent
    action: ActionType
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Optional[dict] = field(default_factory=dict)
