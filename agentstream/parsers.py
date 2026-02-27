"""Parsers for Claude SSE, Claude CLI JSONL, and Codex JSONL stream formats."""

import json
from typing import Optional

from agentstream.events import Agent, ActionType, AgentEvent


class BaseParser:
    """Base class for stream parsers."""

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Claude API SSE parser (raw HTTP streaming)
# ---------------------------------------------------------------------------

class ClaudeSSEParser(BaseParser):
    """Parse Claude Messages API server-sent events.

    For: curl -N https://api.anthropic.com/v1/messages ... | agentstream
    SSE format: event: <type>\\ndata: <json>\\n\\n
    """

    def __init__(self):
        self._event_type: Optional[str] = None
        self._data_lines: list[str] = []
        self._session_id: str = ""

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
            self._session_id = msg.get("id", self._session_id)
            return AgentEvent(
                Agent.CLAUDE, ActionType.MESSAGE_START,
                f"Session started ({model})", session_id=self._session_id,
            )

        elif etype == "content_block_start":
            block = payload.get("content_block", {})
            block_type = block.get("type", "")
            if block_type == "thinking":
                return AgentEvent(Agent.CLAUDE, ActionType.THINKING, "Thinking...",
                                  session_id=self._session_id)
            elif block_type == "tool_use":
                name = block.get("name", "unknown_tool")
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE, f"Calling {name}",
                                  session_id=self._session_id)
            return None

        elif etype == "content_block_delta":
            delta = payload.get("delta", {})
            dt = delta.get("type", "")
            if dt == "text_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.TEXT_DELTA,
                                  delta.get("text", ""), session_id=self._session_id)
            elif dt == "thinking_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.THINKING,
                                  delta.get("thinking", ""), session_id=self._session_id)
            elif dt == "input_json_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE,
                                  delta.get("partial_json", ""), session_id=self._session_id)
            return None

        elif etype == "content_block_stop":
            return None

        elif etype == "message_delta":
            delta = payload.get("delta", {})
            stop = delta.get("stop_reason", "")
            usage = payload.get("usage", {})
            tokens = usage.get("output_tokens", "")
            parts = [p for p in [stop, f"{tokens} tokens" if tokens else ""] if p]
            if parts:
                return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_STOP,
                                  " | ".join(parts), session_id=self._session_id)
            return None

        elif etype == "message_stop":
            return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_STOP, "Complete",
                              session_id=self._session_id)

        elif etype == "ping":
            return None

        elif etype == "error":
            error = payload.get("error", {})
            return AgentEvent(Agent.CLAUDE, ActionType.ERROR,
                              error.get("message", "Unknown error"),
                              session_id=self._session_id)

        return None


# ---------------------------------------------------------------------------
# Claude CLI JSONL parser (claude -p --output-format stream-json)
# ---------------------------------------------------------------------------

class ClaudeCLIParser(BaseParser):
    """Parse Claude Code CLI --output-format stream-json output.

    For: claude -p "task" --output-format stream-json | agentstream
    Each line is a JSON object with 'type' field: system, assistant, user,
    stream_event, result, tool_progress, etc.
    """

    def __init__(self):
        self._session_id: str = ""

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return AgentEvent(Agent.CLAUDE, ActionType.ERROR, f"Bad JSON: {line[:80]}")

        etype = data.get("type", "unknown")
        subtype = data.get("subtype", "")

        # Track session ID from any event that carries it
        sid = data.get("session_id", "")
        if sid:
            self._session_id = sid

        if etype == "system":
            return self._parse_system(subtype, data)
        elif etype == "assistant":
            return self._parse_assistant(data)
        elif etype == "user":
            return self._parse_user(data)
        elif etype == "stream_event":
            return self._parse_stream_event(data)
        elif etype == "result":
            return self._parse_result(data)
        elif etype == "tool_progress":
            name = data.get("tool_name", "")
            elapsed = data.get("elapsed_time_seconds", 0)
            if elapsed > 2:
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE,
                                  f"{name} ({elapsed:.0f}s...)",
                                  session_id=self._session_id)
            return None
        elif etype == "tool_use_summary":
            summary = data.get("summary", "")
            if summary:
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_RESULT,
                                  summary[:200], session_id=self._session_id)
            return None
        elif etype == "rate_limit_event":
            info = data.get("rate_limit_info", {})
            status = info.get("status", "")
            if status == "rejected":
                return AgentEvent(Agent.CLAUDE, ActionType.ERROR,
                                  "Rate limited", session_id=self._session_id)
            return None
        elif etype == "auth_status":
            if data.get("error"):
                return AgentEvent(Agent.CLAUDE, ActionType.ERROR,
                                  f"Auth: {data['error']}", session_id=self._session_id)
            return None

        return None  # Skip unknown types silently

    def _parse_system(self, subtype: str, data: dict) -> Optional[AgentEvent]:
        if subtype == "init":
            model = data.get("model", "unknown")
            tools = data.get("tools", [])
            version = data.get("claude_code_version", "")
            parts = [model]
            if tools:
                parts.append(f"{len(tools)} tools")
            if version:
                parts.append(f"v{version}")
            return AgentEvent(Agent.CLAUDE, ActionType.INIT,
                              " | ".join(parts), session_id=self._session_id)

        elif subtype == "compact_boundary":
            meta = data.get("compact_metadata", {})
            trigger = meta.get("trigger", "auto")
            tokens = meta.get("pre_tokens", 0)
            return AgentEvent(Agent.CLAUDE, ActionType.COMPACT,
                              f"Context compacted ({trigger}, {tokens:,} tokens)",
                              session_id=self._session_id)

        elif subtype == "status":
            status = data.get("status", "")
            if status == "compacting":
                return AgentEvent(Agent.CLAUDE, ActionType.COMPACT,
                                  "Compacting context...", session_id=self._session_id)
            return None

        elif subtype == "task_started":
            desc = data.get("description", "")
            return AgentEvent(Agent.CLAUDE, ActionType.TASK_UPDATE,
                              f"Started: {desc}", session_id=self._session_id)

        elif subtype == "task_notification":
            status = data.get("status", "")
            summary = data.get("summary", "")
            return AgentEvent(Agent.CLAUDE, ActionType.TASK_UPDATE,
                              f"{status}: {summary}"[:150], session_id=self._session_id)

        elif subtype == "task_progress":
            desc = data.get("description", "")
            usage = data.get("usage", {})
            tools = usage.get("tool_uses", 0)
            if tools:
                return AgentEvent(Agent.CLAUDE, ActionType.TASK_UPDATE,
                                  f"{desc} ({tools} tool calls)",
                                  session_id=self._session_id)
            return None

        return None

    def _parse_assistant(self, data: dict) -> Optional[AgentEvent]:
        message = data.get("message", {})
        content = message.get("content", [])

        if not isinstance(content, list):
            return None

        # Return the first meaningful content block
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    return AgentEvent(Agent.CLAUDE, ActionType.TEXT_DELTA,
                                      text[:400], session_id=self._session_id)

            elif block_type == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                inp_str = _summarize_tool_input(name, inp)
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE,
                                  f"{name} {inp_str}", session_id=self._session_id)

            elif block_type == "thinking":
                text = block.get("thinking", "")
                if text:
                    return AgentEvent(Agent.CLAUDE, ActionType.THINKING,
                                      text[:200], session_id=self._session_id)

        return None

    def _parse_user(self, data: dict) -> Optional[AgentEvent]:
        message = data.get("message", {})
        content = message.get("content", [])

        if not isinstance(content, list):
            return None

        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                result_content = block.get("content", "")
                is_error = block.get("is_error", False)
                if is_error:
                    text = result_content if isinstance(result_content, str) else str(result_content)[:100]
                    return AgentEvent(Agent.CLAUDE, ActionType.ERROR,
                                      f"Tool error: {text[:150]}", session_id=self._session_id)
                if isinstance(result_content, str) and result_content.strip():
                    return AgentEvent(Agent.CLAUDE, ActionType.TOOL_RESULT,
                                      result_content[:200], session_id=self._session_id)

        return None

    def _parse_stream_event(self, data: dict) -> Optional[AgentEvent]:
        event = data.get("event", {})
        event_type = event.get("type", "")

        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            dt = delta.get("type", "")
            if dt == "text_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.TEXT_DELTA,
                                  delta.get("text", ""), session_id=self._session_id)
            elif dt == "thinking_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.THINKING,
                                  delta.get("thinking", ""), session_id=self._session_id)
            elif dt == "input_json_delta":
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE,
                                  delta.get("partial_json", ""), session_id=self._session_id)
            return None

        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            bt = block.get("type", "")
            if bt == "tool_use":
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE,
                                  f"Calling {block.get('name', '?')}",
                                  session_id=self._session_id)
            elif bt == "thinking":
                return AgentEvent(Agent.CLAUDE, ActionType.THINKING,
                                  "Thinking...", session_id=self._session_id)
            return None

        elif event_type == "message_start":
            msg = event.get("message", {})
            model = msg.get("model", "")
            if model:
                return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_START,
                                  f"Response ({model})", session_id=self._session_id)
            return None

        elif event_type == "message_delta":
            delta = event.get("delta", {})
            stop = delta.get("stop_reason", "")
            if stop:
                return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_STOP,
                                  stop, session_id=self._session_id)
            return None

        return None

    def _parse_result(self, data: dict) -> Optional[AgentEvent]:
        subtype = data.get("subtype", "")

        if subtype == "success":
            cost = data.get("total_cost_usd", 0)
            turns = data.get("num_turns", 0)
            duration = data.get("duration_ms", 0) / 1000
            usage = data.get("usage", {})
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)

            parts = []
            if turns:
                parts.append(f"{turns} turns")
            if cost:
                parts.append(f"${cost:.4f}")
            if duration:
                parts.append(f"{duration:.1f}s")
            if inp or out:
                parts.append(f"{inp:,}+{out:,} tok")

            return AgentEvent(
                Agent.CLAUDE, ActionType.RESULT, " | ".join(parts),
                session_id=self._session_id,
                metadata={"total_cost_usd": cost, "num_turns": turns},
            )

        elif subtype.startswith("error"):
            errors = data.get("errors", [])
            msg = ", ".join(errors) if errors else subtype
            return AgentEvent(Agent.CLAUDE, ActionType.ERROR, msg,
                              session_id=self._session_id)

        return None


# ---------------------------------------------------------------------------
# Codex CLI JSONL parser (codex exec --json)
# ---------------------------------------------------------------------------

class CodexJSONLParser(BaseParser):
    """Parse Codex CLI --json JSONL output.

    For: codex exec --json "task" | agentstream
    Each line is a JSON object with a 'type' field containing dots.
    """

    def __init__(self):
        self._thread_id: str = ""

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
            self._thread_id = data.get("thread_id", "")
            short_id = self._thread_id[:8] if self._thread_id else "?"
            return AgentEvent(Agent.CODEX, ActionType.THREAD_START,
                              f"Thread {short_id}", session_id=self._thread_id)

        elif etype == "turn.started":
            return AgentEvent(Agent.CODEX, ActionType.TURN_START,
                              "New turn", session_id=self._thread_id)

        elif etype == "turn.completed":
            usage = data.get("usage", {})
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            cached = usage.get("cached_input_tokens", 0)
            parts = [f"{inp:,} in"]
            if cached:
                parts.append(f"{cached:,} cached")
            parts.append(f"{out:,} out")
            return AgentEvent(Agent.CODEX, ActionType.TURN_COMPLETE,
                              " / ".join(parts), session_id=self._thread_id,
                              metadata={"usage": usage})

        elif etype == "turn.failed":
            error = data.get("error", {})
            msg = error.get("message", "Unknown failure")
            return AgentEvent(Agent.CODEX, ActionType.TURN_FAILED,
                              msg, session_id=self._thread_id)

        elif etype in ("item.started", "item.updated", "item.completed"):
            return self._parse_item(etype, data.get("item", {}))

        elif etype == "error":
            msg = data.get("message", data.get("error", str(data)[:80]))
            # Skip transient reconnection notices
            if "Reconnecting" in str(msg):
                return None
            return AgentEvent(Agent.CODEX, ActionType.ERROR,
                              str(msg), session_id=self._thread_id)

        return None

    def _parse_item(self, event_type: str, item: dict) -> Optional[AgentEvent]:
        # Handle both old (item_type) and new (type) field names
        item_type = item.get("type", item.get("item_type", "unknown"))
        is_start = "started" in event_type
        is_complete = "completed" in event_type

        # Normalize old "assistant_message" to new "agent_message"
        if item_type == "assistant_message":
            item_type = "agent_message"

        if item_type == "agent_message":
            text = item.get("text", "")
            if text:
                display = text[:400] + ("..." if len(text) > 400 else "")
                return AgentEvent(Agent.CODEX, ActionType.AGENT_MESSAGE,
                                  display, session_id=self._thread_id)
            return None

        elif item_type == "command_execution":
            cmd = item.get("command", "")
            if is_start and cmd:
                return AgentEvent(Agent.CODEX, ActionType.COMMAND,
                                  cmd, session_id=self._thread_id)
            elif is_complete:
                exit_code = item.get("exit_code")
                output = item.get("aggregated_output", "")
                if exit_code is not None and exit_code != 0:
                    snippet = output[:120] if output else ""
                    return AgentEvent(
                        Agent.CODEX, ActionType.ERROR,
                        f"exit {exit_code}: {cmd} {snippet}".strip(),
                        session_id=self._thread_id,
                    )
                elif output:
                    snippet = output.strip()[:150]
                    return AgentEvent(Agent.CODEX, ActionType.COMMAND,
                                      f"{cmd} -> {snippet}",
                                      session_id=self._thread_id)
            return None

        elif item_type == "file_change":
            changes = item.get("changes", [])
            parts = []
            for c in changes[:4]:
                path = c.get("path", "?")
                kind = c.get("kind", "")
                prefix = {"add": "+", "delete": "-", "update": "~"}.get(kind, "")
                parts.append(f"{prefix}{path}")
            summary = ", ".join(parts)
            if len(changes) > 4:
                summary += f" +{len(changes) - 4} more"
            return AgentEvent(Agent.CODEX, ActionType.FILE_CHANGE,
                              summary, session_id=self._thread_id)

        elif item_type == "reasoning":
            text = item.get("text", item.get("summary", ""))
            if text:
                return AgentEvent(Agent.CODEX, ActionType.REASONING,
                                  text[:200], session_id=self._thread_id)
            return None

        elif item_type == "mcp_tool_call":
            server = item.get("server", "?")
            tool = item.get("tool", "?")
            status = item.get("status", "")
            return AgentEvent(Agent.CODEX, ActionType.MCP_TOOL,
                              f"{server}/{tool} ({status})",
                              session_id=self._thread_id)

        elif item_type == "web_search":
            query = item.get("query", "")
            return AgentEvent(Agent.CODEX, ActionType.WEB_SEARCH,
                              query, session_id=self._thread_id)

        elif item_type == "error":
            msg = item.get("text", item.get("message", "Unknown error"))
            return AgentEvent(Agent.CODEX, ActionType.ERROR,
                              str(msg), session_id=self._thread_id)

        return None


# ---------------------------------------------------------------------------
# Claude interactive session parser (~/.claude/projects/ JSONL files)
# ---------------------------------------------------------------------------

class ClaudeInteractiveParser(BaseParser):
    """Parse Claude Code interactive session JSONL files.

    For: tailing ~/.claude/projects/<project>/<uuid>.jsonl
    Each line is a JSON object with 'type' in: assistant, user, progress,
    system, file-history-snapshot. Uses camelCase sessionId.
    """

    def __init__(self):
        self._session_id: str = ""
        self._slug: str = ""

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None  # Silently skip malformed lines in watch mode

        etype = data.get("type", "")

        # Track session ID (camelCase in interactive format)
        sid = data.get("sessionId", "")
        if sid:
            self._session_id = sid

        # Track slug (human-readable session name)
        slug = data.get("slug", "")
        if slug:
            self._slug = slug

        if etype == "assistant":
            event = self._parse_assistant(data)
        elif etype == "user":
            event = self._parse_user(data)
        elif etype == "progress":
            event = self._parse_progress(data)
        elif etype == "system":
            event = self._parse_system(data)
        elif etype == "file-history-snapshot":
            return None  # Not useful for display
        else:
            return None

        # Attach slug to event metadata so the app can use it for labeling
        if event and self._slug:
            if event.metadata is None:
                event.metadata = {}
            event.metadata["slug"] = self._slug

        return event

    def _parse_assistant(self, data: dict) -> Optional[AgentEvent]:
        message = data.get("message", {})
        content = message.get("content", [])

        if not isinstance(content, list):
            return None

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    return AgentEvent(Agent.CLAUDE, ActionType.TEXT_DELTA,
                                      text[:400], session_id=self._session_id)

            elif block_type == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                inp_str = _summarize_tool_input(name, inp)
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE,
                                  f"{name} {inp_str}", session_id=self._session_id)

            elif block_type == "thinking":
                text = block.get("thinking", "")
                if text:
                    return AgentEvent(Agent.CLAUDE, ActionType.THINKING,
                                      text[:200], session_id=self._session_id)

        return None

    def _parse_user(self, data: dict) -> Optional[AgentEvent]:
        message = data.get("message", {})
        content = message.get("content", "")

        # Plain string = user typed a prompt
        if isinstance(content, str) and content.strip():
            return AgentEvent(Agent.CLAUDE, ActionType.USER_PROMPT,
                              content.strip()[:200], session_id=self._session_id)

        # Array = tool results
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    is_error = block.get("is_error", False)
                    result_content = block.get("content", "")
                    if is_error:
                        text = result_content if isinstance(result_content, str) else str(result_content)[:100]
                        return AgentEvent(Agent.CLAUDE, ActionType.ERROR,
                                          f"Tool error: {text[:150]}",
                                          session_id=self._session_id)
                    if isinstance(result_content, str) and result_content.strip():
                        return AgentEvent(Agent.CLAUDE, ActionType.TOOL_RESULT,
                                          result_content[:200],
                                          session_id=self._session_id)

        return None

    def _parse_progress(self, data: dict) -> Optional[AgentEvent]:
        progress = data.get("data", {})
        ptype = progress.get("type", "")

        if ptype == "hook_progress":
            return None  # Too noisy

        if ptype == "bash_progress":
            elapsed = progress.get("elapsedTimeSeconds", 0)
            if elapsed >= 3:
                output = progress.get("output", "")
                snippet = output[:80] if output else f"running ({elapsed}s)"
                return AgentEvent(Agent.CLAUDE, ActionType.TOOL_USE,
                                  f"Bash {snippet}", session_id=self._session_id)
            return None

        if ptype == "agent_progress":
            prompt = progress.get("prompt", "")
            if prompt:
                return AgentEvent(Agent.CLAUDE, ActionType.TASK_UPDATE,
                                  f"Subagent: {prompt[:120]}",
                                  session_id=self._session_id)
            return None

        return None

    def _parse_system(self, data: dict) -> Optional[AgentEvent]:
        subtype = data.get("subtype", "")
        if subtype == "stop_hook_summary":
            return AgentEvent(Agent.CLAUDE, ActionType.MESSAGE_STOP,
                              "Session hook stopped", session_id=self._session_id)
        return None


# ---------------------------------------------------------------------------
# Codex interactive session parser (~/.codex/sessions/ JSONL files)
# ---------------------------------------------------------------------------

class CodexInteractiveParser(BaseParser):
    """Parse Codex interactive session JSONL files.

    For: tailing ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
    Each line is a JSON object with 'type' in: session_meta, event_msg,
    response_item, turn_context.  Data is nested inside a 'payload' object.
    """

    def __init__(self):
        self._session_id: str = ""
        self._model: str = ""
        self._cwd_project: str = ""

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None  # Silently skip malformed lines in watch mode

        etype = data.get("type", "")
        payload = data.get("payload", {})

        if etype == "session_meta":
            event = self._parse_session_meta(payload)
        elif etype == "event_msg":
            event = self._parse_event_msg(payload)
        elif etype == "response_item":
            event = self._parse_response_item(payload)
        elif etype == "turn_context":
            # Extract model for tracking
            model = payload.get("model", "")
            if model:
                self._model = model
            return None
        else:
            return None

        # Attach cwd_project to all events so the app can label the session
        if event and self._cwd_project:
            if event.metadata is None:
                event.metadata = {}
            event.metadata["cwd_project"] = self._cwd_project

        return event

    def _parse_session_meta(self, payload: dict) -> Optional[AgentEvent]:
        session_id = payload.get("id", "")
        if session_id:
            self._session_id = session_id

        cwd = payload.get("cwd", "")
        version = payload.get("cli_version", "")
        provider = payload.get("model_provider", "")

        # Extract project name from cwd (last path segment)
        if cwd:
            self._cwd_project = cwd.rstrip("/").rsplit("/", 1)[-1] if "/" in cwd else cwd

        parts = [provider or "codex"]
        if version:
            parts.append(f"v{version}")
        if cwd:
            parts.append(cwd)

        return AgentEvent(
            Agent.CODEX, ActionType.INIT,
            " | ".join(parts), session_id=self._session_id,
        )

    def _parse_event_msg(self, payload: dict) -> Optional[AgentEvent]:
        event_type = payload.get("type", "")

        if event_type == "task_started":
            return AgentEvent(Agent.CODEX, ActionType.TURN_START,
                              "New turn", session_id=self._session_id)

        elif event_type == "user_message":
            text = payload.get("message", "")
            if text:
                return AgentEvent(Agent.CODEX, ActionType.USER_PROMPT,
                                  str(text)[:200], session_id=self._session_id)
            return None

        elif event_type == "agent_reasoning":
            text = payload.get("text", "")
            if text:
                return AgentEvent(Agent.CODEX, ActionType.REASONING,
                                  str(text)[:200], session_id=self._session_id)
            return None

        elif event_type == "agent_message":
            text = payload.get("message", "")
            if text:
                return AgentEvent(Agent.CODEX, ActionType.AGENT_MESSAGE,
                                  str(text)[:400], session_id=self._session_id)
            return None

        elif event_type == "task_complete":
            last_msg = payload.get("last_agent_message", "")
            snippet = str(last_msg)[:200] if last_msg else "Done"
            return AgentEvent(Agent.CODEX, ActionType.TURN_COMPLETE,
                              snippet, session_id=self._session_id)

        elif event_type == "token_count":
            return None  # Too noisy

        return None

    def _parse_response_item(self, payload: dict) -> Optional[AgentEvent]:
        item_type = payload.get("type", "")

        if item_type == "function_call":
            name = payload.get("name", "")
            args_raw = payload.get("arguments", "")
            cmd = _extract_codex_command(args_raw)
            display = f"{name} {cmd}" if name else str(cmd)
            return AgentEvent(Agent.CODEX, ActionType.COMMAND,
                              display[:200], session_id=self._session_id)

        elif item_type == "function_call_output":
            output = payload.get("output", "")
            return AgentEvent(Agent.CODEX, ActionType.TOOL_RESULT,
                              str(output)[:200], session_id=self._session_id)

        elif item_type == "custom_tool_call":
            name = payload.get("name", payload.get("tool", "?"))
            return AgentEvent(Agent.CODEX, ActionType.TOOL_USE,
                              name, session_id=self._session_id)

        elif item_type == "custom_tool_call_output":
            output = payload.get("output", "")
            return AgentEvent(Agent.CODEX, ActionType.TOOL_RESULT,
                              str(output)[:200], session_id=self._session_id)

        elif item_type == "reasoning":
            # summary is a list of objects with 'text' fields
            summary = payload.get("summary", [])
            if isinstance(summary, list) and summary:
                texts = [s.get("text", "") for s in summary if isinstance(s, dict)]
                text = " ".join(t for t in texts if t)
            else:
                text = str(summary) if summary else ""
            if text:
                return AgentEvent(Agent.CODEX, ActionType.REASONING,
                                  text[:200], session_id=self._session_id)
            return None

        elif item_type == "message":
            return None  # System/developer noise

        return None


# ---------------------------------------------------------------------------
# Auto-detect parser
# ---------------------------------------------------------------------------

class AutoDetectParser(BaseParser):
    """Auto-detects format from the first meaningful line.

    Distinguishes:
    - Claude API SSE: lines start with 'event:' or 'data:'
    - Claude CLI JSONL: JSON with type in (system, assistant, user, result, stream_event, ...)
    - Codex CLI JSONL: JSON with type containing dots (thread.started, turn.started, ...)
    """

    CLAUDE_CLI_TYPES = frozenset({
        "system", "assistant", "user", "result", "stream_event",
        "tool_progress", "tool_use_summary", "auth_status",
        "rate_limit_event", "prompt_suggestion",
    })

    def __init__(self):
        self._delegate: Optional[BaseParser] = None

    def parse_line(self, line: str) -> Optional[AgentEvent]:
        if self._delegate is None:
            stripped = line.strip()
            if not stripped:
                return None

            # SSE format (Claude API)
            if stripped.startswith("event:") or stripped.startswith("data:"):
                self._delegate = ClaudeSSEParser()

            # JSON format - distinguish Claude CLI vs Codex
            elif stripped.startswith("{"):
                try:
                    data = json.loads(stripped)
                    etype = data.get("type", "")
                    if "." in etype:
                        self._delegate = CodexJSONLParser()
                    elif etype in self.CLAUDE_CLI_TYPES:
                        self._delegate = ClaudeCLIParser()
                    else:
                        # Default to Codex if has "item" field, Claude CLI otherwise
                        if "item" in data or "thread_id" in data:
                            self._delegate = CodexJSONLParser()
                        else:
                            self._delegate = ClaudeCLIParser()
                except json.JSONDecodeError:
                    return None
            else:
                return None

        return self._delegate.parse_line(line)

    @property
    def detected_format(self) -> Optional[str]:
        if isinstance(self._delegate, ClaudeSSEParser):
            return "claude-sse"
        elif isinstance(self._delegate, ClaudeCLIParser):
            return "claude-cli"
        elif isinstance(self._delegate, CodexJSONLParser):
            return "codex"
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_tool_input(name: str, inp: dict) -> str:
    """Create a short summary of tool input for display."""
    if not inp:
        return ""
    # Common Claude Code tool patterns
    if name in ("Read", "Glob", "Grep"):
        path = inp.get("file_path", inp.get("path", inp.get("pattern", "")))
        return str(path)[:80] if path else json.dumps(inp)[:80]
    elif name in ("Edit", "Write"):
        path = inp.get("file_path", "")
        return str(path)[:80] if path else json.dumps(inp)[:80]
    elif name == "Bash":
        cmd = inp.get("command", "")
        return str(cmd)[:80] if cmd else json.dumps(inp)[:80]
    elif name == "Task":
        prompt = inp.get("prompt", inp.get("description", ""))
        return str(prompt)[:80] if prompt else json.dumps(inp)[:80]
    else:
        return json.dumps(inp)[:80]


def _extract_codex_command(args_raw: str | dict) -> str:
    """Extract a command string from Codex function_call arguments."""
    if isinstance(args_raw, str):
        try:
            args_data = json.loads(args_raw)
            return str(args_data.get("cmd", args_data.get("command", args_raw[:200])))
        except (json.JSONDecodeError, AttributeError):
            return args_raw[:200]
    elif isinstance(args_raw, dict):
        return str(args_raw.get("cmd", args_raw.get("command", str(args_raw)[:200])))
    return str(args_raw)[:200]


def create_parser(agent_type: str) -> BaseParser:
    """Create a parser for the given agent type."""
    if agent_type == "claude":
        return ClaudeCLIParser()
    elif agent_type == "claude-sse":
        return ClaudeSSEParser()
    elif agent_type == "claude-interactive":
        return ClaudeInteractiveParser()
    elif agent_type == "codex":
        return CodexJSONLParser()
    elif agent_type == "codex-interactive":
        return CodexInteractiveParser()
    else:
        return AutoDetectParser()
