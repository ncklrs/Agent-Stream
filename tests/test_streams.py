"""Tests for AgentStream stream sources."""

import asyncio
import json
import tempfile
import os

import pytest

from agentstream.events import Agent, ActionType
from agentstream.streams import demo_stream, file_stream, exec_stream


@pytest.mark.asyncio
async def test_demo_stream_yields_events():
    """Demo stream should yield STREAM_START then agent events."""
    events = []
    async for event in demo_stream():
        events.append(event)
        if len(events) >= 10:
            break

    assert events[0].action == ActionType.STREAM_START
    assert events[0].agent == Agent.SYSTEM

    agents_seen = {e.agent for e in events[1:]}
    assert Agent.CLAUDE in agents_seen or Agent.CODEX in agents_seen


@pytest.mark.asyncio
async def test_demo_stream_has_session_ids():
    """Demo events should carry session IDs."""
    events = []
    async for event in demo_stream():
        events.append(event)
        if len(events) >= 15:
            break

    session_ids = {e.session_id for e in events if e.session_id}
    assert len(session_ids) >= 1


@pytest.mark.asyncio
async def test_file_stream_not_found():
    """file_stream should yield error for missing file."""
    events = []
    async for event in file_stream("auto", "/tmp/nonexistent_agentstream_test_file"):
        events.append(event)
        if event.action in (ActionType.ERROR, ActionType.STREAM_END):
            break

    actions = [e.action for e in events]
    assert ActionType.STREAM_START in actions
    assert ActionType.ERROR in actions


@pytest.mark.asyncio
async def test_file_stream_reads_new_lines():
    """file_stream should pick up lines appended to a file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    try:
        events = []

        async def collect():
            async for event in file_stream("codex", path):
                events.append(event)
                if len(events) >= 3:
                    break

        task = asyncio.create_task(collect())

        # Give file_stream time to start and seek to end
        await asyncio.sleep(0.3)

        # Append a Codex event
        with open(path, "a") as f:
            f.write(json.dumps({"type": "thread.started", "thread_id": "t1"}) + "\n")

        # Wait for it to be picked up
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        actions = [e.action for e in events]
        assert ActionType.STREAM_START in actions
        assert ActionType.THREAD_START in actions
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_exec_stream_empty_command():
    """exec_stream should yield error for empty command."""
    events = []
    async for event in exec_stream("auto", ""):
        events.append(event)

    assert len(events) == 1
    assert events[0].action == ActionType.ERROR
    assert "Empty" in events[0].content


@pytest.mark.asyncio
async def test_exec_stream_runs_command():
    """exec_stream should capture stdout from a subprocess."""
    cmd = 'echo \'{"type":"thread.started","thread_id":"t1"}\''
    events = []
    async for event in exec_stream("codex", cmd):
        events.append(event)

    actions = [e.action for e in events]
    assert ActionType.STREAM_START in actions
    assert ActionType.THREAD_START in actions
    assert ActionType.STREAM_END in actions


@pytest.mark.asyncio
async def test_exec_stream_nonzero_exit():
    """exec_stream should report non-zero exit codes."""
    events = []
    async for event in exec_stream("auto", "exit 42"):
        events.append(event)

    actions = [e.action for e in events]
    assert ActionType.STREAM_END in actions
    end_event = [e for e in events if e.action == ActionType.STREAM_END][0]
    assert "42" in end_event.content
