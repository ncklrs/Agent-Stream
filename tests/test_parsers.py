"""Tests for AgentStream parsers."""

import json
import pytest

from agentstream.events import Agent, ActionType
from agentstream.theme import session_color, SESSION_PALETTE
from agentstream.parsers import (
    ClaudeCLIParser,
    ClaudeSSEParser,
    ClaudeInteractiveParser,
    CodexJSONLParser,
    CodexInteractiveParser,
    AutoDetectParser,
    create_parser,
)


# ---------------------------------------------------------------------------
# Claude CLI Parser
# ---------------------------------------------------------------------------

class TestClaudeCLIParser:

    def test_system_init(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "system", "subtype": "init",
            "model": "claude-sonnet-4-6", "tools": ["Read", "Write"],
            "claude_code_version": "2.1.0", "session_id": "sess-abc",
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.agent == Agent.CLAUDE
        assert ev.action == ActionType.INIT
        assert "claude-sonnet-4-6" in ev.content
        assert "2 tools" in ev.content
        assert ev.session_id == "sess-abc"

    def test_assistant_text(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello world"}]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TEXT_DELTA
        assert "Hello world" in ev.content

    def test_assistant_tool_use(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "name": "Read",
                "input": {"file_path": "/tmp/foo.py"},
            }]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_USE
        assert "Read" in ev.content
        assert "/tmp/foo.py" in ev.content

    def test_assistant_thinking(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "Let me think"}]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.THINKING

    def test_user_tool_result(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "user",
            "message": {"content": [{
                "type": "tool_result", "content": "file contents here",
            }]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_RESULT

    def test_user_tool_error(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "user",
            "message": {"content": [{
                "type": "tool_result", "content": "File not found",
                "is_error": True,
            }]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_result_success(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "result", "subtype": "success",
            "total_cost_usd": 0.0342, "num_turns": 3,
            "duration_ms": 14200,
            "usage": {"input_tokens": 12847, "output_tokens": 1203},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.RESULT
        assert "$0.0342" in ev.content
        assert ev.metadata["total_cost_usd"] == 0.0342

    def test_result_error(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "result", "subtype": "error_max_turns",
            "errors": ["Hit turn limit"],
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_stream_event_text_delta(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "streaming..."},
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TEXT_DELTA
        assert "streaming..." in ev.content

    def test_compact_boundary(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "system", "subtype": "compact_boundary",
            "compact_metadata": {"trigger": "auto", "pre_tokens": 50000},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.COMPACT
        assert "50,000" in ev.content

    def test_rate_limit_rejected(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "rejected"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_rate_limit_ok_ignored(self):
        p = ClaudeCLIParser()
        line = json.dumps({
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "ok"},
        })
        ev = p.parse_line(line)
        assert ev is None

    def test_empty_line_ignored(self):
        p = ClaudeCLIParser()
        assert p.parse_line("") is None
        assert p.parse_line("   ") is None

    def test_bad_json(self):
        p = ClaudeCLIParser()
        ev = p.parse_line("{broken json")
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_unknown_type_ignored(self):
        p = ClaudeCLIParser()
        ev = p.parse_line(json.dumps({"type": "future_new_type"}))
        assert ev is None

    def test_session_id_tracking(self):
        p = ClaudeCLIParser()
        p.parse_line(json.dumps({
            "type": "system", "subtype": "init",
            "model": "sonnet", "session_id": "s123",
        }))
        ev = p.parse_line(json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "hi"}]},
        }))
        assert ev.session_id == "s123"


# ---------------------------------------------------------------------------
# Codex JSONL Parser
# ---------------------------------------------------------------------------

class TestCodexJSONLParser:

    def test_thread_started(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "thread.started",
            "thread_id": "abcdef1234567890",
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.agent == Agent.CODEX
        assert ev.action == ActionType.THREAD_START
        assert "abcdef12" in ev.content
        assert ev.session_id == "abcdef1234567890"

    def test_turn_started(self):
        p = CodexJSONLParser()
        p.parse_line(json.dumps({"type": "thread.started", "thread_id": "t1"}))
        ev = p.parse_line(json.dumps({"type": "turn.started"}))
        assert ev is not None
        assert ev.action == ActionType.TURN_START
        assert ev.session_id == "t1"

    def test_turn_completed(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "turn.completed",
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TURN_COMPLETE
        assert "1,000 in" in ev.content

    def test_turn_failed(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "turn.failed",
            "error": {"message": "Something broke"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TURN_FAILED
        assert "Something broke" in ev.content

    def test_item_agent_message(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "All tests passed"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.AGENT_MESSAGE
        assert "All tests passed" in ev.content

    def test_item_assistant_message_normalized(self):
        """Old 'assistant_message' type should be normalized to agent_message."""
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "Done"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.AGENT_MESSAGE

    def test_item_command_started(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.started",
            "item": {"type": "command_execution", "command": "npm test"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.COMMAND
        assert "npm test" in ev.content

    def test_item_command_completed_failure(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.completed",
            "item": {
                "type": "command_execution", "command": "npm build",
                "exit_code": 1, "aggregated_output": "Error: module not found",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_item_file_change(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.completed",
            "item": {
                "type": "file_change",
                "changes": [
                    {"path": "src/app.py", "kind": "update"},
                    {"path": "src/new.py", "kind": "add"},
                ],
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.FILE_CHANGE
        assert "~src/app.py" in ev.content
        assert "+src/new.py" in ev.content

    def test_item_reasoning(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.completed",
            "item": {"type": "reasoning", "text": "Analyzing codebase"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.REASONING

    def test_item_mcp_tool(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.completed",
            "item": {"type": "mcp_tool_call", "server": "docs", "tool": "search", "status": "done"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.MCP_TOOL
        assert "docs/search" in ev.content

    def test_item_web_search(self):
        p = CodexJSONLParser()
        line = json.dumps({
            "type": "item.completed",
            "item": {"type": "web_search", "query": "python async best practices"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.WEB_SEARCH

    def test_error_event(self):
        p = CodexJSONLParser()
        line = json.dumps({"type": "error", "message": "API error"})
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_reconnecting_ignored(self):
        p = CodexJSONLParser()
        line = json.dumps({"type": "error", "message": "Reconnecting..."})
        ev = p.parse_line(line)
        assert ev is None

    def test_bad_json(self):
        p = CodexJSONLParser()
        ev = p.parse_line("not json at all")
        assert ev is not None
        assert ev.action == ActionType.ERROR
        assert ev.agent == Agent.CODEX


# ---------------------------------------------------------------------------
# Claude SSE Parser
# ---------------------------------------------------------------------------

class TestClaudeSSEParser:

    def _feed(self, parser, event_type, data):
        """Helper to feed a complete SSE event."""
        parser.parse_line(f"event: {event_type}\n")
        parser.parse_line(f"data: {json.dumps(data)}\n")
        return parser.parse_line("\n")

    def test_message_start(self):
        p = ClaudeSSEParser()
        ev = self._feed(p, "message_start", {
            "type": "message_start",
            "message": {"id": "msg_123", "model": "claude-sonnet-4-6"},
        })
        assert ev is not None
        assert ev.action == ActionType.MESSAGE_START
        assert "claude-sonnet-4-6" in ev.content
        assert ev.session_id == "msg_123"

    def test_text_delta(self):
        p = ClaudeSSEParser()
        ev = self._feed(p, "content_block_delta", {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello"},
        })
        assert ev is not None
        assert ev.action == ActionType.TEXT_DELTA
        assert ev.content == "Hello"

    def test_thinking_block_start(self):
        p = ClaudeSSEParser()
        ev = self._feed(p, "content_block_start", {
            "type": "content_block_start",
            "content_block": {"type": "thinking"},
        })
        assert ev is not None
        assert ev.action == ActionType.THINKING

    def test_tool_use_block_start(self):
        p = ClaudeSSEParser()
        ev = self._feed(p, "content_block_start", {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Read"},
        })
        assert ev is not None
        assert ev.action == ActionType.TOOL_USE
        assert "Read" in ev.content

    def test_message_stop(self):
        p = ClaudeSSEParser()
        ev = self._feed(p, "message_stop", {"type": "message_stop"})
        assert ev is not None
        assert ev.action == ActionType.MESSAGE_STOP

    def test_error_event(self):
        p = ClaudeSSEParser()
        ev = self._feed(p, "error", {
            "type": "error",
            "error": {"message": "Overloaded"},
        })
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_ping_ignored(self):
        p = ClaudeSSEParser()
        ev = self._feed(p, "ping", {"type": "ping"})
        assert ev is None

    def test_bad_json_data(self):
        p = ClaudeSSEParser()
        p.parse_line("event: message_start\n")
        p.parse_line("data: {broken\n")
        ev = p.parse_line("\n")
        assert ev is not None
        assert ev.action == ActionType.ERROR


# ---------------------------------------------------------------------------
# Claude Interactive Parser
# ---------------------------------------------------------------------------

class TestClaudeInteractiveParser:

    def test_assistant_text(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "assistant",
            "sessionId": "fa32-abcd",
            "message": {"content": [{"type": "text", "text": "Hello world"}]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.agent == Agent.CLAUDE
        assert ev.action == ActionType.TEXT_DELTA
        assert "Hello world" in ev.content
        assert ev.session_id == "fa32-abcd"

    def test_assistant_tool_use(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "assistant",
            "sessionId": "s1",
            "message": {"content": [{
                "type": "tool_use", "name": "Read",
                "input": {"file_path": "/tmp/foo.py"},
            }]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_USE
        assert "Read" in ev.content
        assert "/tmp/foo.py" in ev.content

    def test_assistant_thinking(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "Let me think"}]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.THINKING

    def test_user_plain_prompt(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "user",
            "sessionId": "s1",
            "message": {"content": "Fix the login bug"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.USER_PROMPT
        assert "Fix the login bug" in ev.content

    def test_user_tool_result(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "user",
            "message": {"content": [{
                "type": "tool_result", "content": "file contents here",
            }]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_RESULT

    def test_user_tool_error(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "user",
            "message": {"content": [{
                "type": "tool_result", "content": "File not found",
                "is_error": True,
            }]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.ERROR

    def test_progress_hook_ignored(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "progress",
            "data": {"type": "hook_progress"},
        })
        ev = p.parse_line(line)
        assert ev is None

    def test_progress_bash_short_ignored(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "progress",
            "data": {"type": "bash_progress", "elapsedTimeSeconds": 1},
        })
        ev = p.parse_line(line)
        assert ev is None

    def test_progress_bash_long_shown(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "progress",
            "data": {"type": "bash_progress", "elapsedTimeSeconds": 5, "output": "building..."},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_USE
        assert "Bash" in ev.content

    def test_progress_agent(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "progress",
            "data": {"type": "agent_progress", "prompt": "Research auth patterns"},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TASK_UPDATE
        assert "Subagent" in ev.content

    def test_file_history_snapshot_ignored(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "file-history-snapshot",
            "messageId": "abc",
            "snapshot": {},
        })
        ev = p.parse_line(line)
        assert ev is None

    def test_system_stop_hook(self):
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "system",
            "subtype": "stop_hook_summary",
            "sessionId": "s1",
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.MESSAGE_STOP

    def test_session_id_camelcase_tracking(self):
        """Interactive format uses camelCase sessionId."""
        p = ClaudeInteractiveParser()
        p.parse_line(json.dumps({
            "type": "assistant",
            "sessionId": "sess-xyz",
            "message": {"content": [{"type": "text", "text": "hi"}]},
        }))
        # Subsequent event should inherit session_id
        ev = p.parse_line(json.dumps({
            "type": "user",
            "message": {"content": "follow up"},
        }))
        assert ev.session_id == "sess-xyz"

    def test_slug_in_metadata(self):
        """Slug (session name) is extracted into event metadata."""
        p = ClaudeInteractiveParser()
        line = json.dumps({
            "type": "assistant",
            "sessionId": "s1",
            "slug": "sparkling-crafting-hummingbird",
            "message": {"content": [{"type": "text", "text": "hi"}]},
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.metadata["slug"] == "sparkling-crafting-hummingbird"

    def test_empty_line_ignored(self):
        p = ClaudeInteractiveParser()
        assert p.parse_line("") is None
        assert p.parse_line("   ") is None

    def test_bad_json_silently_skipped(self):
        """Interactive parser silently skips bad JSON (unlike CLI parser)."""
        p = ClaudeInteractiveParser()
        ev = p.parse_line("{broken json")
        assert ev is None


# ---------------------------------------------------------------------------
# Codex Interactive Parser
# ---------------------------------------------------------------------------

class TestCodexInteractiveParser:

    def test_session_meta(self):
        """Init event extracts provider, version, and cwd."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "timestamp": "2026-02-27T17:30:21.663Z",
            "type": "session_meta",
            "payload": {
                "id": "019ca026-b34c-7390",
                "cwd": "/Users/nick/Dev/my-project",
                "cli_version": "0.106.0",
                "model_provider": "openai",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.agent == Agent.CODEX
        assert ev.action == ActionType.INIT
        assert "openai" in ev.content
        assert "v0.106.0" in ev.content
        assert "/Users/nick/Dev/my-project" in ev.content
        assert ev.session_id == "019ca026-b34c-7390"

    def test_user_message(self):
        """User prompt is extracted from event_msg/user_message."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "Fix the login bug",
                "images": [],
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.USER_PROMPT
        assert "Fix the login bug" in ev.content

    def test_agent_message(self):
        """Agent text is extracted from event_msg/agent_message."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "message": "I'll check the current branch now.",
                "phase": "commentary",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.AGENT_MESSAGE
        assert "check the current branch" in ev.content

    def test_agent_reasoning(self):
        """Reasoning text from event_msg/agent_reasoning."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "agent_reasoning",
                "text": "**Preparing to get current branch**",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.REASONING
        assert "Preparing to get current branch" in ev.content

    def test_function_call(self):
        """Command extraction from response_item/function_call arguments."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": '{"cmd":"git branch --show-current","workdir":"/tmp"}',
                "call_id": "call_abc123",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.COMMAND
        assert "exec_command" in ev.content
        assert "git branch --show-current" in ev.content

    def test_function_call_output(self):
        """Tool result strips Codex metadata wrapper and shows clean output."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_abc123",
                "output": "Chunk ID: a74dfd\nWall time: 0.05 seconds\nProcess exited with code 0\nOriginal token count: 7\nOutput:\nMT-533-portal-components\n",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_RESULT
        assert "MT-533-portal-components" in ev.content
        # Metadata should be stripped
        assert "Chunk ID" not in ev.content
        assert "Wall time" not in ev.content
        assert "Process exited" not in ev.content

    def test_function_call_output_error(self):
        """Non-zero exit code maps to ERROR action."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_abc123",
                "output": "Chunk ID: x\nWall time: 1.0 seconds\nProcess exited with code 1\nOriginal token count: 20\nOutput:\nError: module not found\n",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.ERROR
        assert "module not found" in ev.content

    def test_function_call_output_plain(self):
        """Output without Codex wrapper is passed through as-is."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_abc123",
                "output": "plain output text",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_RESULT
        assert "plain output text" in ev.content

    def test_task_started(self):
        """Turn lifecycle: task_started → TURN_START."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-abc",
                "model_context_window": 258400,
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TURN_START
        assert "New turn" in ev.content

    def test_task_complete(self):
        """Turn lifecycle: task_complete → TURN_COMPLETE."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-abc",
                "last_agent_message": "`MT-533-portal-components`",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TURN_COMPLETE
        assert "MT-533" in ev.content

    def test_token_count_skipped(self):
        """token_count events are silently skipped."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "event_msg",
            "payload": {"type": "token_count", "info": None},
        })
        ev = p.parse_line(line)
        assert ev is None

    def test_response_item_message_skipped(self):
        """System/developer message response_items are skipped."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "system prompt"}],
            },
        })
        ev = p.parse_line(line)
        assert ev is None

    def test_turn_context_extracts_model(self):
        """turn_context is used for model tracking only (returns None)."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-abc",
                "model": "gpt-5.3-codex",
                "cwd": "/tmp",
            },
        })
        ev = p.parse_line(line)
        assert ev is None
        # Model should be tracked internally
        assert p._model == "gpt-5.3-codex"

    def test_reasoning_response_item(self):
        """reasoning response_item extracts summary text."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "Analyzing codebase"},
                ],
                "content": None,
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.REASONING
        assert "Analyzing codebase" in ev.content

    def test_custom_tool_call(self):
        """custom_tool_call maps to TOOL_USE."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "read_file",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_USE
        assert "read_file" in ev.content

    def test_custom_tool_call_output(self):
        """custom_tool_call_output maps to TOOL_RESULT."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "output": "file contents here",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.action == ActionType.TOOL_RESULT
        assert "file contents" in ev.content

    def test_bad_json_silently_skipped(self):
        """Interactive parser silently skips bad JSON."""
        p = CodexInteractiveParser()
        ev = p.parse_line("{broken json")
        assert ev is None

    def test_empty_line_ignored(self):
        p = CodexInteractiveParser()
        assert p.parse_line("") is None
        assert p.parse_line("   ") is None

    def test_cwd_project_in_metadata(self):
        """Project name is derived from cwd and attached to event metadata."""
        p = CodexInteractiveParser()
        line = json.dumps({
            "type": "session_meta",
            "payload": {
                "id": "sess-123",
                "cwd": "/Users/nick/Dev/my-project",
                "cli_version": "0.106.0",
            },
        })
        ev = p.parse_line(line)
        assert ev is not None
        assert ev.metadata["cwd_project"] == "my-project"

    def test_cwd_project_persists_across_events(self):
        """Once cwd_project is set from session_meta, it's on all events."""
        p = CodexInteractiveParser()
        # First: session_meta sets cwd_project
        p.parse_line(json.dumps({
            "type": "session_meta",
            "payload": {
                "id": "sess-123",
                "cwd": "/Users/nick/Dev/my-project",
                "cli_version": "0.1.0",
            },
        }))
        # Second: a different event should also have cwd_project
        ev = p.parse_line(json.dumps({
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "hi"},
        }))
        assert ev is not None
        assert ev.metadata["cwd_project"] == "my-project"

    def test_session_id_tracking(self):
        """Session ID from session_meta persists to subsequent events."""
        p = CodexInteractiveParser()
        p.parse_line(json.dumps({
            "type": "session_meta",
            "payload": {"id": "sess-abc", "cwd": "/tmp"},
        }))
        ev = p.parse_line(json.dumps({
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "hello"},
        }))
        assert ev.session_id == "sess-abc"


# ---------------------------------------------------------------------------
# Auto-detect parser
# ---------------------------------------------------------------------------

class TestAutoDetectParser:

    def test_detects_claude_cli(self):
        p = AutoDetectParser()
        line = json.dumps({"type": "system", "subtype": "init", "model": "sonnet"})
        ev = p.parse_line(line)
        assert ev is not None
        assert p.detected_format == "claude-cli"

    def test_detects_codex(self):
        p = AutoDetectParser()
        line = json.dumps({"type": "thread.started", "thread_id": "t1"})
        ev = p.parse_line(line)
        assert ev is not None
        assert p.detected_format == "codex"

    def test_detects_sse(self):
        p = AutoDetectParser()
        p.parse_line("event: message_start\n")
        assert p.detected_format == "claude-sse"

    def test_empty_lines_skipped(self):
        p = AutoDetectParser()
        assert p.parse_line("") is None
        assert p.parse_line("   ") is None
        assert p.detected_format is None

    def test_subsequent_lines_delegated(self):
        p = AutoDetectParser()
        p.parse_line(json.dumps({"type": "thread.started", "thread_id": "t1"}))
        ev = p.parse_line(json.dumps({"type": "turn.started"}))
        assert ev is not None
        assert ev.action == ActionType.TURN_START

    def test_fallback_to_claude_cli(self):
        """Unknown JSON type without dots should default to Claude CLI."""
        p = AutoDetectParser()
        ev = p.parse_line(json.dumps({"type": "something_new", "data": "test"}))
        assert p.detected_format == "claude-cli"

    def test_fallback_codex_by_item_field(self):
        """JSON with 'item' field should detect as Codex."""
        p = AutoDetectParser()
        p.parse_line(json.dumps({"type": "unknown", "item": {"type": "test"}}))
        assert p.detected_format == "codex"


# ---------------------------------------------------------------------------
# create_parser factory
# ---------------------------------------------------------------------------

class TestCreateParser:

    def test_claude(self):
        p = create_parser("claude")
        assert isinstance(p, ClaudeCLIParser)

    def test_claude_sse(self):
        p = create_parser("claude-sse")
        assert isinstance(p, ClaudeSSEParser)

    def test_claude_interactive(self):
        p = create_parser("claude-interactive")
        assert isinstance(p, ClaudeInteractiveParser)

    def test_codex(self):
        p = create_parser("codex")
        assert isinstance(p, CodexJSONLParser)

    def test_codex_interactive(self):
        p = create_parser("codex-interactive")
        assert isinstance(p, CodexInteractiveParser)

    def test_auto(self):
        p = create_parser("auto")
        assert isinstance(p, AutoDetectParser)

    def test_unknown_defaults_to_auto(self):
        p = create_parser("whatever")
        assert isinstance(p, AutoDetectParser)


# ---------------------------------------------------------------------------
# Session color assignment
# ---------------------------------------------------------------------------

class TestSessionColor:

    def test_deterministic(self):
        """Same session_id always returns the same color."""
        c1 = session_color("sess-abc-123")
        c2 = session_color("sess-abc-123")
        assert c1 == c2

    def test_returns_palette_pair(self):
        """Result is always a valid (primary, dim) pair from the palette."""
        primary, dim = session_color("any-id")
        assert (primary, dim) in SESSION_PALETTE

    def test_different_ids_can_differ(self):
        """Different session IDs can map to different colors."""
        colors = {session_color(f"session-{i}") for i in range(20)}
        # With 20 different IDs over an 8-color palette, we expect >1 distinct color
        assert len(colors) > 1
