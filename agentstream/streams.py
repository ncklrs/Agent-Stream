"""Stream sources for AgentStream.

Each source is an async generator that yields AgentEvent objects.
"""

import asyncio
import os
import pathlib
import sys
import time
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


# ---------------------------------------------------------------------------
# Watch stream (auto-discover active Claude interactive sessions)
# ---------------------------------------------------------------------------

_CLAUDE_PROJECTS_DIR = pathlib.Path.home() / ".claude" / "projects"
_SCAN_INTERVAL = 5.0       # seconds between discovery scans
_SESSION_MAX_AGE = 600.0   # 10 min — ignore files older than this
_TAIL_IDLE_TIMEOUT = 600.0 # 10 min — stop tailing after no new data


def _discover_sessions() -> list[pathlib.Path]:
    """Find active JSONL session files under ~/.claude/projects/."""
    if not _CLAUDE_PROJECTS_DIR.is_dir():
        return []

    cutoff = time.time() - _SESSION_MAX_AGE
    found: list[pathlib.Path] = []

    for project_dir in _CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        # Top-level session files: <uuid>.jsonl
        for f in project_dir.glob("*.jsonl"):
            if f.stat().st_mtime >= cutoff:
                found.append(f)
        # Subagent files: <uuid>/subagents/agent-*.jsonl
        for f in project_dir.glob("*/subagents/agent-*.jsonl"):
            if f.stat().st_mtime >= cutoff:
                found.append(f)

    return found


def _extract_project_name(session_path: pathlib.Path) -> str:
    """Extract a readable project name from the session file path.

    The project dir is like `-Users-nick-Dev-Agent-Stream`.
    We take the last path segment after the final `-Dev-` or just the last part.
    """
    # The project dir is either the parent (top-level) or grandparent (subagent)
    if session_path.parent.name == "subagents":
        project_dir = session_path.parent.parent.parent
    else:
        project_dir = session_path.parent

    name = project_dir.name
    # Try to extract the last meaningful segment
    # Pattern: -Users-foo-Dev-ProjectName or -Users-foo-some-path
    parts = name.split("-")
    # Find last non-empty segment
    if parts:
        # Skip leading empty from the dash prefix
        clean = [p for p in parts if p]
        if clean:
            return clean[-1]
    return name[:16]


async def _tail_session_file(
    path: pathlib.Path,
    queue: asyncio.Queue,
    project_name: str,
) -> None:
    """Tail a session JSONL file and push parsed events into the queue."""
    parser = create_parser("claude-interactive")

    # Notify discovery
    await queue.put(AgentEvent(
        Agent.SYSTEM, ActionType.STREAM_START,
        f"Watching {project_name}/{path.stem[:8]}",
    ))

    try:
        with open(path, "r") as f:
            # Seek to end to only show new events
            f.seek(0, 2)
            last_data_time = time.time()

            while True:
                line = f.readline()
                if not line:
                    if time.time() - last_data_time > _TAIL_IDLE_TIMEOUT:
                        await queue.put(AgentEvent(
                            Agent.SYSTEM, ActionType.STREAM_END,
                            f"Session idle: {project_name}/{path.stem[:8]}",
                        ))
                        return
                    await asyncio.sleep(0.15)
                    continue

                last_data_time = time.time()
                event = parser.parse_line(line)
                if event:
                    if event.metadata is None:
                        event.metadata = {}
                    event.metadata["project_name"] = project_name
                    await queue.put(event)

    except asyncio.CancelledError:
        return
    except Exception as e:
        await queue.put(AgentEvent(
            Agent.SYSTEM, ActionType.ERROR,
            f"Watch error ({project_name}): {e}",
        ))


async def watch_stream() -> AsyncGenerator[AgentEvent, None]:
    """Auto-discover and tail active Claude interactive sessions."""
    yield AgentEvent(Agent.SYSTEM, ActionType.STREAM_START,
                     "Watch mode — scanning for active Claude sessions")

    queue: asyncio.Queue = asyncio.Queue()
    # Map path -> asyncio.Task to avoid duplicate tails
    active_tails: dict[str, asyncio.Task] = {}

    try:
        while True:
            # Discover sessions
            sessions = _discover_sessions()

            if not sessions and not active_tails:
                yield AgentEvent(Agent.SYSTEM, ActionType.PING,
                                 "Scanning for active sessions...")

            # Spawn tail tasks for newly discovered sessions
            for path in sessions:
                key = str(path)
                if key not in active_tails or active_tails[key].done():
                    project_name = _extract_project_name(path)
                    task = asyncio.create_task(
                        _tail_session_file(path, queue, project_name)
                    )
                    active_tails[key] = task

            # Clean up finished tasks
            done_keys = [k for k, t in active_tails.items() if t.done()]
            for k in done_keys:
                del active_tails[k]

            # Drain all queued events
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                    yield event
                except asyncio.QueueEmpty:
                    break

            # Wait before next scan, but keep draining the queue
            deadline = asyncio.get_event_loop().time() + _SCAN_INTERVAL
            while asyncio.get_event_loop().time() < deadline:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.2)
                    yield event
                except (asyncio.TimeoutError, TimeoutError):
                    continue

    except asyncio.CancelledError:
        # Cancel all tail tasks
        for task in active_tails.values():
            task.cancel()
        if active_tails:
            await asyncio.gather(*active_tails.values(), return_exceptions=True)
        return
