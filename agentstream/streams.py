"""Stream sources for AgentStream.

Each source is an async generator that yields AgentEvent objects.
"""

import asyncio
import sys
from typing import AsyncGenerator

from agentstream.events import Agent, ActionType, AgentEvent
from agentstream.parsers import create_parser


# ---------------------------------------------------------------------------
# Demo stream
# ---------------------------------------------------------------------------

# (delay_seconds, agent, action, content, session_key)
# session_key: "c" = Claude session, "x" = Codex session, "s" = system
DEMO_SCRIPT: list[tuple[float, Agent, ActionType, str, str]] = [
    # --- Claude session starts ---
    (0.6, Agent.CLAUDE, ActionType.INIT, "claude-sonnet-4-6 | 24 tools | v2.1.0", "c"),
    (0.8, Agent.CLAUDE, ActionType.THINKING, "Analyzing the user's request for code refactoring...", "c"),
    (0.5, Agent.CLAUDE, ActionType.THINKING, "I should examine the existing codebase structure first", "c"),

    # --- Codex session starts ---
    (0.7, Agent.CODEX, ActionType.THREAD_START, "Thread a7f3b201", "x"),
    (0.4, Agent.CODEX, ActionType.TURN_START, "New turn", "x"),
    (0.3, Agent.CODEX, ActionType.REASONING, "Searching for Python files in the project", "x"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "find src/ -name '*.py' -type f | head -20", "x"),
    (0.8, Agent.CODEX, ActionType.AGENT_MESSAGE, "Found 14 Python files in src/ directory", "x"),

    # --- Claude responds with tools ---
    (0.6, Agent.CLAUDE, ActionType.TEXT_DELTA, "I'll help you refactor the authentication module.", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "Let me first examine the current implementation.", "c"),
    (0.5, Agent.CLAUDE, ActionType.TOOL_USE, "Read src/auth/handler.py", "c"),
    (0.4, Agent.CLAUDE, ActionType.TOOL_RESULT, "class AuthHandler:\n    def validate_token(self, token)...", "c"),

    # --- Codex runs tests ---
    (0.6, Agent.CODEX, ActionType.COMMAND, "python -m pytest tests/ -q", "x"),
    (0.7, Agent.CODEX, ActionType.AGENT_MESSAGE, "23 passed, 2 warnings in 1.4s", "x"),

    # --- Claude analysis ---
    (0.5, Agent.CLAUDE, ActionType.TEXT_DELTA, "The current auth handler has several issues:", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "1. Token validation is mixed with route handling", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "2. No rate limiting on login attempts", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "3. Session management could be more efficient", "c"),
    (0.4, Agent.CLAUDE, ActionType.TOOL_USE, "Edit src/auth/handler.py", "c"),
    (0.3, Agent.CLAUDE, ActionType.TOOL_RESULT, "Applied 3 edits to handler.py", "c"),

    # --- Codex makes file changes ---
    (0.6, Agent.CODEX, ActionType.FILE_CHANGE, "~src/auth/handler.py, +src/auth/middleware.py", "x"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "python -m pytest tests/ -q", "x"),
    (0.6, Agent.CODEX, ActionType.AGENT_MESSAGE, "25 passed (2 new), 0 warnings", "x"),
    (0.4, Agent.CODEX, ActionType.TURN_COMPLETE, "2,891 in / 456 out", "x"),

    # --- Claude continues ---
    (0.5, Agent.CLAUDE, ActionType.TOOL_USE, "Write src/auth/session.py", "c"),
    (0.3, Agent.CLAUDE, ActionType.TOOL_RESULT, "Created src/auth/session.py (87 lines)", "c"),
    (0.4, Agent.CLAUDE, ActionType.TEXT_DELTA, "Created an optimized session manager using Redis.", "c"),
    (0.3, Agent.CLAUDE, ActionType.MESSAGE_STOP, "end_turn | 847 tokens", "c"),

    # --- Codex second turn: build failure + recovery ---
    (0.7, Agent.CODEX, ActionType.TURN_START, "New turn", "x"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "npm run build", "x"),
    (0.8, Agent.CODEX, ActionType.ERROR, "Build failed: Cannot find module 'redis'", "x"),
    (0.4, Agent.CODEX, ActionType.COMMAND, "npm install redis", "x"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "npm run build", "x"),
    (0.4, Agent.CODEX, ActionType.AGENT_MESSAGE, "Build succeeded after installing redis", "x"),
    (0.3, Agent.CODEX, ActionType.TURN_COMPLETE, "1,203 in / 189 out", "x"),

    # --- Claude task update + follow-up ---
    (0.5, Agent.CLAUDE, ActionType.MESSAGE_START, "Follow-up response", "c"),
    (0.4, Agent.CLAUDE, ActionType.TEXT_DELTA, "All changes have been applied successfully.", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "The auth module now has:", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "- Separated token validation (handler.py)", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "- Rate limiting middleware (middleware.py)", "c"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "- Redis-backed sessions (session.py)", "c"),
    (0.4, Agent.CLAUDE, ActionType.MESSAGE_STOP, "end_turn | 312 tokens", "c"),

    # --- Codex web search + MCP ---
    (0.6, Agent.CODEX, ActionType.TURN_START, "New turn", "x"),
    (0.5, Agent.CODEX, ActionType.WEB_SEARCH, "redis session best practices python", "x"),
    (0.6, Agent.CODEX, ActionType.MCP_TOOL, "docs-server/search_docs (completed)", "x"),
    (0.5, Agent.CODEX, ActionType.AGENT_MESSAGE, "Applied security hardening from Redis docs", "x"),
    (0.4, Agent.CODEX, ActionType.FILE_CHANGE, "~src/auth/session.py (+12, -3)", "x"),
    (0.3, Agent.CODEX, ActionType.TURN_COMPLETE, "3,412 in / 287 out", "x"),

    # --- Claude final result ---
    (0.6, Agent.CLAUDE, ActionType.RESULT, "3 turns | $0.0342 | 14.2s | 12,847+1,203 tok", "c"),
]

DEMO_CLAUDE_SESSION = "demo-cl-a1b2c3d4"
DEMO_CODEX_SESSION = "demo-cx-e5f6a7b8"


async def demo_stream() -> AsyncGenerator[AgentEvent, None]:
    """Yield simulated demo events with realistic timing."""
    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START,
                     "Demo mode - streaming simulated events")

    session_map = {"c": DEMO_CLAUDE_SESSION, "x": DEMO_CODEX_SESSION, "s": ""}

    while True:
        for delay, agent, action, content, key in DEMO_SCRIPT:
            await asyncio.sleep(delay)
            yield AgentEvent(
                agent=agent, action=action, content=content,
                session_id=session_map.get(key, ""),
            )
        yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_END,
                         "Demo cycle complete, restarting...")
        await asyncio.sleep(3.0)


# ---------------------------------------------------------------------------
# Stdin stream
# ---------------------------------------------------------------------------

async def stdin_stream(agent_type: str) -> AsyncGenerator[AgentEvent, None]:
    """Read events from stdin (piped data)."""
    parser = create_parser(agent_type)
    loop = asyncio.get_running_loop()

    agent_label = agent_type if agent_type != "auto" else "stdin"
    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START,
                     f"Reading from stdin ({agent_label})")

    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            event = parser.parse_line(line)
            if event:
                yield event
    except asyncio.CancelledError:
        return
    except Exception as e:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"stdin error: {e}")

    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_END, "stdin stream ended")


# ---------------------------------------------------------------------------
# File watcher stream
# ---------------------------------------------------------------------------

async def file_stream(agent_type: str, path: str) -> AsyncGenerator[AgentEvent, None]:
    """Tail a file and yield events as new lines appear."""
    parser = create_parser(agent_type)

    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START, f"Watching {path}")

    try:
        with open(path, "r") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                event = parser.parse_line(line)
                if event:
                    yield event
    except asyncio.CancelledError:
        return
    except FileNotFoundError:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"File not found: {path}")
    except Exception as e:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"File error: {e}")

    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_END, f"Stopped watching {path}")


# ---------------------------------------------------------------------------
# Subprocess exec stream
# ---------------------------------------------------------------------------

async def _drain_stderr(proc: asyncio.subprocess.Process) -> str:
    """Read stderr in background to prevent pipe deadlocks."""
    if proc.stderr:
        data = await proc.stderr.read()
        return data.decode(errors="replace").strip()
    return ""


async def exec_stream(agent_type: str, cmd: str) -> AsyncGenerator[AgentEvent, None]:
    """Run a command as subprocess and yield events from its stdout."""
    if not cmd or not cmd.strip():
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, "Empty command")
        return

    parser = create_parser(agent_type)

    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START, f"Running: {cmd}")

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )

        # Drain stderr concurrently to prevent pipe deadlock
        stderr_task = asyncio.ensure_future(_drain_stderr(proc))

        if proc.stdout:
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace")
                event = parser.parse_line(line)
                if event:
                    yield event

        exit_code = await proc.wait()
        stderr_text = await stderr_task

        if exit_code != 0 and stderr_text:
            yield AgentEvent(Agent.SYSTEM, ActionType.ERROR,
                             f"Process stderr: {stderr_text[:200]}")

        yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_END,
                         f"Process exited ({exit_code})")
    except asyncio.CancelledError:
        return
    except FileNotFoundError:
        cmd_name = cmd.split()[0] if cmd.split() else cmd
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR,
                         f"Command not found: {cmd_name}")
    except Exception as e:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"Exec error: {e}")
