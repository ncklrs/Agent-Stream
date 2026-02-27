"""Parsers for Claude SSE and Codex JSONL stream formats."""

import json
from typing import Optional

from agentstream.events import Agent, ActionType, AgentEvent


class BaseParser:
    """Base class for stream parsers."""

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        raise NotImplementedError


class ClaudeSSEParser(BaseParser):
    """Parse Claude API server-sent events into AgentEvents.

    SSE format:
        event: <type>
        data: <json>
        <blank line>
    """

    def __init__(self):
        self._event_type: Optional[str] = None
        self._data_lines: list[str] = []

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        line = line.rstrip("\r\n")

        if line.startswith("event: "):
            self._event_type = line[7:]
            return None
        elif line.startswith("data: "):
            self._data_lines.append(line[6:])
            return None
        elif line == "":
            if self._data_lines:
                data_str = "\n".join(self._data_lines)
                event = self._process(self._event_type, data_str)
                self._event_type = None
                self._data_lines = []
                return event
            return None
        else:
            return None

    def _process(self, event_type: Optional[str], data: str) -> Optional[AgentEvent]:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return AgentEvent(Agent.CLAUDE, ActionType.ERROR, f"Bad JSON: {data[:80]}")

        etype = payload.get("type", event_type or "unknown")

        if etype == "message_start":
            msg = payload.get("message", {})
            model = msg.get("model", "unknown")
            return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_START, f"Session started ({model})")

        elif etype == "content_block_start":
            block = payload.get("content_block", {})
            block_type = block.get("type", "unknown")
            if block_type == "thinking":
                return AgentEvent(Agent.CLAUDE, ActionType.THINKING, "Thinking...")
            elif block_type == "tool_use":
                name = block.get("name", "unknown_tool")
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE, f"Calling {name}")
            return None

        elif etype == "content_block_delta":
            delta = payload.get("delta", {})
            delta_type = delta.get("type", "unknown")
            if delta_type == "text_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.TEXT_DELTA, delta.get("text", ""))
            elif delta_type == "thinking_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.THINKING, delta.get("thinking", ""))
            elif delta_type == "input_json_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE, delta.get("partial_json", ""))
            elif delta_type == "signature_delta":
                return None
            return None

        elif etype == "content_block_stop":
            return None

        elif etype == "message_delta":
            delta = payload.get("delta", {})
            stop_reason = delta.get("stop_reason", "")
            usage = payload.get("usage", {})
            tokens = usage.get("output_tokens", "")
            parts = []
            if stop_reason:
                parts.append(stop_reason)
            if tokens:
                parts.append(f"{tokens} tokens")
            if parts:
                return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_STOP, " | ".join(parts))
            return None

        elif etype == "message_stop":
            return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_STOP, "Message complete")

        elif etype == "ping":
            return None  # Skip pings in display

        elif etype == "error":
            error = payload.get("error", {})
            msg = error.get("message", "Unknown error")
            return AgentEvent(Agent.CLAUDE, ActionType.ERROR, msg)

        else:
            return AgentEvent(Agent.CLAUDE, ActionType.UNKNOWN, f"{etype}")


class CodexJSONLParser(BaseParser):
    """Parse Codex CLI JSONL output into AgentEvents.

    Each line is a complete JSON object with a 'type' field.
    """

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return AgentEvent(Agent.CODEX, ActionType.ERROR, f"Bad JSON: {line[:80]}")

        etype = data.get("type", "unknown")

        if etype == "thread.started":
            tid = data.get("thread_id", "")
            short_id = tid[:8] if tid else "?"
            return AgentEvent(Agent.CODEX, ActionType.THREAD_START, f"Thread {short_id}")

        elif etype == "turn.started":
            return AgentEvent(Agent.CODEX, ActionType.TURN_START, "New turn")

        elif etype == "turn.completed":
            usage = data.get("usage", {})
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            cached = usage.get("cached_input_tokens", 0)
            parts = [f"{inp:,} in"]
            if cached:
                parts.append(f"{cached:,} cached")
            parts.append(f"{out:,} out")
            return AgentEvent(Agent.CODEX, ActionType.TURN_COMPLETE, " / ".join(parts))

        elif etype == "turn.failed":
            error = data.get("error", {})
            msg = error.get("message", "Unknown failure")
            return AgentEvent(Agent.CODEX, ActionType.TURN_FAILED, msg)

        elif etype in ("item.started", "item.updated", "item.completed"):
            return self._parse_item(etype, data.get("item", {}))

        elif etype == "error":
            msg = data.get("message", data.get("error", str(data)[:80]))
            return AgentEvent(Agent.CODEX, ActionType.ERROR, str(msg))

        else:
            return AgentEvent(Agent.CODEX, ActionType.UNKNOWN, etype)

    def _parse_item(self, event_type: str, item: dict) -> Optional[AgentEvent]:
        item_type = item.get("type", "unknown")
        is_start = "started" in event_type
        is_complete = "completed" in event_type

        if item_type == "agent_message":
            text = item.get("text", "")
            if text:
                # Truncate long messages for display
                display = text[:300] + ("..." if len(text) > 300 else "")
                return AgentEvent(Agent.CODEX, ActionType.AGENT_MESSAGE, display)
            return None

        elif item_type == "command_execution":
            cmd = item.get("command", "")
            if is_start and cmd:
                return AgentEvent(Agent.CODEX, ActionType.COMMAND, cmd)
            elif is_complete:
                exit_code = item.get("exit_code")
                output = item.get("aggregated_output", "")
                if exit_code is not None and exit_code != 0:
                    snippet = output[:120] if output else ""
                    return AgentEvent(
                        Agent.CODEX, ActionType.ERROR,
                        f"exit {exit_code}: {cmd} {snippet}".strip()
                    )
                elif output:
                    snippet = output.strip()[:150]
                    return AgentEvent(Agent.CODEX, ActionType.COMMAND, f"{cmd} -> {snippet}")
            return None

        elif item_type == "file_change":
            changes = item.get("changes", [])
            paths = [c.get("path", "?") for c in changes[:4]]
            summary = ", ".join(paths)
            if len(changes) > 4:
                summary += f" +{len(changes) - 4} more"
            return AgentEvent(Agent.CODEX, ActionType.FILE_CHANGE, summary)

        elif item_type == "reasoning":
            summary = item.get("summary", "")
            content = item.get("content", "")
            text = summary or content
            if text:
                return AgentEvent(Agent.CODEX, ActionType.REASONING, text[:200])
            return None

        elif item_type == "mcp_tool_call":
            server = item.get("server", "?")
            tool = item.get("tool", "?")
            status = item.get("status", "")
            return AgentEvent(Agent.CODEX, ActionType.MCP_TOOL, f"{server}/{tool} ({status})")

        elif item_type == "web_search":
            query = item.get("query", "")
            return AgentEvent(Agent.CODEX, ActionType.WEB_SEARCH, query)

        elif item_type == "error":
            msg = item.get("text", item.get("message", "Unknown error"))
            return AgentEvent(Agent.CODEX, ActionType.ERROR, str(msg))

        else:
            return None  # Skip unknown item types quietly


class AutoDetectParser(BaseParser):
    """Auto-detects Claude SSE vs Codex JSONL from the first meaningful line."""

    def __init__(self):
        self._delegate: Optional[BaseParser] = None

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        if self._delegate is None:
            stripped = line.strip()
            if not stripped:
                return None
            if stripped.startswith("event:") or stripped.startswith("data:"):
                self._delegate = ClaudeSSEParser()
            elif stripped.startswith("{"):
                self._delegate = CodexJSONLParser()
            else:
                return None  # Can't detect yet

        return self._delegate.parse_line(line)

    @property
    def detected_agent(self) -> Optional[str]:
        if isinstance(self._delegate, ClaudeSSEParser):
            return "claude"
        elif isinstance(self._delegate, CodexJSONLParser):
            return "codex"
        return None


def create_parser(agent_type: str) -> BaseParser:
    """Create a parser for the given agent type."""
    if agent_type == "claude":
        return ClaudeSSEParser()
    elif agent_type == "codex":
        return CodexJSONLParser()
    else:
        return AutoDetectParser()
