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

DEMO_SCRIPT: list[tuple[float, Agent, ActionType, str]] = [
    # --- Claude starts a session ---
    (0.6, Agent.CLAUDE, ActionType.MESSAGE_START, "Session started (claude-sonnet-4-6)"),
    (0.8, Agent.CLAUDE, ActionType.THINKING, "Analyzing the user's request for code refactoring..."),
    (0.5, Agent.CLAUDE, ActionType.THINKING, "I should examine the existing codebase structure first"),

    # --- Codex kicks off ---
    (0.7, Agent.CODEX, ActionType.THREAD_START, "Thread a7f3b201"),
    (0.4, Agent.CODEX, ActionType.TURN_START, "New turn"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "find src/ -name '*.py' -type f | head -20"),
    (0.8, Agent.CODEX, ActionType.AGENT_MESSAGE, "Found 14 Python files in src/ directory"),

    # --- Claude responds ---
    (0.6, Agent.CLAUDE, ActionType.TEXT_DELTA, "I'll help you refactor the authentication module."),
    (0.4, Agent.CLAUDE, ActionType.TEXT_DELTA, "Let me first examine the current implementation."),
    (0.5, Agent.CLAUDE, ActionType.TOOL_USE, "read_file {\"path\": \"src/auth/handler.py\"}"),

    # --- Codex runs tests ---
    (0.6, Agent.CODEX, ActionType.COMMAND, "python -m pytest tests/ -q"),
    (0.7, Agent.CODEX, ActionType.AGENT_MESSAGE, "23 passed, 2 warnings in 1.4s"),

    # --- Claude analysis ---
    (0.5, Agent.CLAUDE, ActionType.TEXT_DELTA, "The current auth handler has several issues:"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "1. Token validation is mixed with route handling"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "2. No rate limiting on login attempts"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "3. Session management could be more efficient"),

    # --- Codex makes changes ---
    (0.6, Agent.CODEX, ActionType.FILE_CHANGE, "src/auth/handler.py (+28, -15)"),
    (0.4, Agent.CODEX, ActionType.FILE_CHANGE, "src/auth/middleware.py (+45, -0)"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "python -m pytest tests/ -q"),
    (0.6, Agent.CODEX, ActionType.AGENT_MESSAGE, "25 passed (2 new), 0 warnings"),
    (0.4, Agent.CODEX, ActionType.TURN_COMPLETE, "2,891 in / 456 out"),

    # --- Claude continues ---
    (0.5, Agent.CLAUDE, ActionType.TOOL_USE, "write_file {\"path\": \"src/auth/session.py\"}"),
    (0.4, Agent.CLAUDE, ActionType.TEXT_DELTA, "Created an optimized session manager using Redis."),
    (0.3, Agent.CLAUDE, ActionType.MESSAGE_STOP, "end_turn | 847 tokens"),

    # --- Codex second turn: build failure + recovery ---
    (0.7, Agent.CODEX, ActionType.TURN_START, "New turn"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "npm run build"),
    (0.8, Agent.CODEX, ActionType.ERROR, "Build failed: Cannot find module 'redis'"),
    (0.4, Agent.CODEX, ActionType.COMMAND, "npm install redis"),
    (0.5, Agent.CODEX, ActionType.COMMAND, "npm run build"),
    (0.4, Agent.CODEX, ActionType.AGENT_MESSAGE, "Build succeeded after installing redis"),
    (0.3, Agent.CODEX, ActionType.TURN_COMPLETE, "1,203 in / 189 out"),

    # --- Claude follow-up ---
    (0.6, Agent.CLAUDE, ActionType.MESSAGE_START, "Follow-up response"),
    (0.4, Agent.CLAUDE, ActionType.TEXT_DELTA, "All changes have been applied successfully."),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "The auth module now has:"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "- Separated token validation (handler.py)"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "- Rate limiting middleware (middleware.py)"),
    (0.3, Agent.CLAUDE, ActionType.TEXT_DELTA, "- Redis-backed sessions (session.py)"),
    (0.4, Agent.CLAUDE, ActionType.MESSAGE_STOP, "end_turn | 312 tokens"),

    # --- Codex web search + MCP ---
    (0.6, Agent.CODEX, ActionType.TURN_START, "New turn"),
    (0.5, Agent.CODEX, ActionType.WEB_SEARCH, "redis session best practices python"),
    (0.6, Agent.CODEX, ActionType.MCP_TOOL, "docs-server/search_docs (completed)"),
    (0.5, Agent.CODEX, ActionType.AGENT_MESSAGE, "Applied security hardening from Redis docs"),
    (0.4, Agent.CODEX, ActionType.FILE_CHANGE, "src/auth/session.py (+12, -3)"),
    (0.3, Agent.CODEX, ActionType.TURN_COMPLETE, "3,412 in / 287 out"),
]


async def demo_stream() -> AsyncGenerator[AgentEvent, None]:
    """Yield simulated demo events with realistic timing."""
    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START, "Demo mode - streaming simulated events")
    while True:
        for delay, agent, action, content in DEMO_SCRIPT:
            await asyncio.sleep(delay)
            yield AgentEvent(agent=agent, action=action, content=content)
        # Pause between loops
        yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_END, "Demo cycle complete, restarting...")
        await asyncio.sleep(3.0)


# ---------------------------------------------------------------------------
# Stdin stream
# ---------------------------------------------------------------------------

async def stdin_stream(agent_type: str) -> AsyncGenerator[AgentEvent, None]:
    """Read events from stdin (piped data)."""
    parser = create_parser(agent_type)
    loop = asyncio.get_running_loop()

    agent_label = agent_type if agent_type != "auto" else "stdin"
    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START, f"Reading from stdin ({agent_label})")

    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            event = parser.parse_line(line)
            if event:
                yield event
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
            # Seek to end - only show new events
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                event = parser.parse_line(line)
                if event:
                    yield event
    except FileNotFoundError:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"File not found: {path}")
    except Exception as e:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"File error: {e}")


# ---------------------------------------------------------------------------
# Subprocess exec stream
# ---------------------------------------------------------------------------

async def exec_stream(agent_type: str, cmd: str) -> AsyncGenerator[AgentEvent, None]:
    """Run a command as subprocess and yield events from its stdout."""
    parser = create_parser(agent_type)

    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START, f"Running: {cmd}")

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )

        if proc.stdout:
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace")
                event = parser.parse_line(line)
                if event:
                    yield event

        exit_code = await proc.wait()

        if exit_code != 0 and proc.stderr:
            stderr = await proc.stderr.read()
            stderr_text = stderr.decode(errors="replace").strip()
            if stderr_text:
                yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"Process stderr: {stderr_text[:200]}")

        yield AgentEvent(
            Agent.SYSTEM, ActionType.STREAM_END,
            f"Process exited ({exit_code})"
        )
    except FileNotFoundError:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"Command not found: {cmd.split()[0]}")
    except Exception as e:
        yield AgentEvent(Agent.SYSTEM, ActionType.ERROR, f"Exec error: {e}")
