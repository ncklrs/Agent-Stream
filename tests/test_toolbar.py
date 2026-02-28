"""Tests for AgentStream toolbar components.

Tests the EventBuffer, HTTP handler, and serialization logic
that don't require macOS or rumps.
"""

import json
import queue
import threading
import time
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from agentstream.events import Agent, ActionType, AgentEvent


# ---------------------------------------------------------------------------
# EventBuffer tests
# ---------------------------------------------------------------------------

from agentstream.toolbar import EventBuffer, _event_to_dict


def _make_event(
    agent=Agent.CLAUDE,
    action=ActionType.TEXT,
    content="hello",
    session_id="sess-1",
    metadata=None,
):
    return AgentEvent(
        agent=agent,
        action=action,
        content=content,
        session_id=session_id,
        metadata=metadata or {},
    )


class TestEventBuffer:
    def test_append_and_counter(self):
        buf = EventBuffer(maxlen=100)
        assert buf.counter == 0

        buf.append(_make_event())
        assert buf.counter == 1

        buf.append(_make_event())
        assert buf.counter == 2

    def test_get_all_events(self):
        buf = EventBuffer(maxlen=100)
        e1 = _make_event(content="first")
        e2 = _make_event(content="second")
        buf.append(e1)
        buf.append(e2)

        events = buf.get_all_events()
        assert len(events) == 2
        assert events[0].content == "first"
        assert events[1].content == "second"

    def test_get_events_since(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(content="a"))
        buf.append(_make_event(content="b"))
        buf.append(_make_event(content="c"))

        since_1 = buf.get_events_since(1)
        assert len(since_1) == 2
        assert since_1[0][1].content == "b"
        assert since_1[1][1].content == "c"

        since_3 = buf.get_events_since(3)
        assert len(since_3) == 0

    def test_maxlen_eviction(self):
        buf = EventBuffer(maxlen=3)
        for i in range(5):
            buf.append(_make_event(content=str(i)))

        events = buf.get_all_events()
        assert len(events) == 3
        assert events[0].content == "2"
        assert events[2].content == "4"

    def test_session_registration(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id="s1", metadata={"slug": "sparkling-hummingbird"}))
        buf.append(_make_event(session_id="s1"))

        sessions = buf.get_sessions()
        assert "s1" in sessions
        assert sessions["s1"].display_name == "hummingbird"
        assert sessions["s1"].event_count == 2

    def test_session_name_from_project(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id="s2", metadata={"project_name": "MyProject"}))

        sessions = buf.get_sessions()
        assert sessions["s2"].display_name == "MyProject"

    def test_session_name_from_cwd_project(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id="s3", metadata={"cwd_project": "cwd-proj"}))

        sessions = buf.get_sessions()
        assert sessions["s3"].display_name == "cwd-proj"

    def test_session_name_fallback_to_id(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id="abcdef12-3456"))

        sessions = buf.get_sessions()
        assert sessions["abcdef12-3456"].display_name == "abcdef12"

    def test_demo_session_name(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id="demo-cl-abc"))

        sessions = buf.get_sessions()
        assert sessions["demo-cl-abc"].display_name == "Demo"

    def test_session_color_assigned(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id="color-test"))

        sessions = buf.get_sessions()
        assert sessions["color-test"].color != ""
        assert sessions["color-test"].color_dim != ""

    def test_session_cost_tracking(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id="s1", metadata={"total_cost_usd": 0.01}))
        buf.append(_make_event(session_id="s1", metadata={"total_cost_usd": 0.02}))

        sessions = buf.get_sessions()
        assert abs(sessions["s1"].total_cost - 0.03) < 1e-9

    def test_no_session_for_empty_id(self):
        buf = EventBuffer(maxlen=100)
        buf.append(_make_event(session_id=""))

        sessions = buf.get_sessions()
        assert len(sessions) == 0

    def test_sse_subscriber_receives_events(self):
        buf = EventBuffer(maxlen=100)
        q = buf.subscribe_sse()

        buf.append(_make_event(content="live"))

        seq, event = q.get(timeout=1)
        assert event.content == "live"
        assert seq == 1

    def test_sse_subscriber_full_queue(self):
        buf = EventBuffer(maxlen=2000)
        q = buf.subscribe_sse()

        # Fill the queue (maxsize=500) — should not raise
        for i in range(600):
            buf.append(_make_event(content=str(i)))

        # Queue should have capped at 500
        count = 0
        while not q.empty():
            q.get_nowait()
            count += 1
        assert count == 500

    def test_sse_unsubscribe(self):
        buf = EventBuffer(maxlen=100)
        q = buf.subscribe_sse()
        buf.unsubscribe_sse(q)

        # After unsubscribe, new events should not reach the queue
        buf.append(_make_event())
        assert q.empty()

    def test_sse_unsubscribe_unknown_queue(self):
        buf = EventBuffer(maxlen=100)
        # Should not raise
        buf.unsubscribe_sse(queue.Queue())

    def test_thread_safety(self):
        buf = EventBuffer(maxlen=500)
        errors = []

        def writer():
            try:
                for i in range(200):
                    buf.append(_make_event(content=str(i), session_id=f"s{i % 5}"))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    buf.get_sessions()
                    buf.get_all_events()
                    buf.get_events_since(0)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        assert buf.counter == 400


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------

class TestEventSerialization:
    def test_event_to_dict_basic(self):
        event = _make_event(content="test content")
        d = _event_to_dict(event)

        assert d["agent"] == "claude"
        assert d["action"] == "text"
        assert d["content"] == "test content"
        assert d["session_id"] == "sess-1"
        assert "timestamp" in d
        assert isinstance(d["metadata"], dict)

    def test_event_to_dict_empty_content(self):
        event = _make_event(content="")
        d = _event_to_dict(event)
        assert d["content"] == ""

    def test_event_to_dict_none_metadata(self):
        event = AgentEvent(
            agent=Agent.SYSTEM,
            action=ActionType.PING,
            content="ping",
            metadata=None,
        )
        d = _event_to_dict(event)
        assert d["metadata"] == {}

    def test_event_to_dict_json_roundtrip(self):
        event = _make_event(metadata={"slug": "test-slug", "cost": 0.01})
        d = _event_to_dict(event)
        serialized = json.dumps(d)
        restored = json.loads(serialized)

        assert restored["agent"] == "claude"
        assert restored["metadata"]["slug"] == "test-slug"

    def test_event_to_dict_all_agents(self):
        for agent in Agent:
            event = _make_event(agent=agent)
            d = _event_to_dict(event)
            assert d["agent"] == agent.value

    def test_event_to_dict_all_actions(self):
        for action in ActionType:
            event = _make_event(action=action)
            d = _event_to_dict(event)
            assert d["action"] == action.value


# ---------------------------------------------------------------------------
# Panel HTML tests
# ---------------------------------------------------------------------------

from agentstream.toolbar import PANEL_HTML


class TestPanelHTML:
    def test_html_is_valid_string(self):
        assert isinstance(PANEL_HTML, str)
        assert len(PANEL_HTML) > 100

    def test_html_has_doctype(self):
        assert PANEL_HTML.strip().startswith("<!DOCTYPE html>")

    def test_html_has_sse_endpoint(self):
        assert "/events" in PANEL_HTML

    def test_html_has_history_endpoint(self):
        assert "/api/history" in PANEL_HTML

    def test_html_has_sessions_endpoint(self):
        assert "/api/sessions" in PANEL_HTML

    def test_html_has_event_source(self):
        assert "EventSource" in PANEL_HTML

    def test_html_has_dark_theme(self):
        assert "#0f0f17" in PANEL_HTML  # bg-dark color


# ---------------------------------------------------------------------------
# Port finder test
# ---------------------------------------------------------------------------

from agentstream.toolbar import _find_port


class TestFindPort:
    def test_find_port_returns_int(self):
        port = _find_port(range(18900, 18910))
        assert isinstance(port, int)
        assert 18900 <= port <= 18909

    def test_find_port_skips_busy(self):
        import socket

        # Occupy a port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 18950))
        s.listen(1)
        try:
            port = _find_port(range(18950, 18955))
            assert port is not None
            assert port != 18950
        finally:
            s.close()

    def test_find_port_returns_none_when_all_busy(self):
        import socket

        sockets = []
        try:
            for p in range(18960, 18963):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", p))
                s.listen(1)
                sockets.append(s)

            port = _find_port(range(18960, 18963))
            assert port is None
        finally:
            for s in sockets:
                s.close()


# ---------------------------------------------------------------------------
# Notify action set test
# ---------------------------------------------------------------------------

from agentstream.toolbar import _NOTIFY_ACTIONS


class TestNotifyActions:
    def test_notify_actions_contains_errors(self):
        assert ActionType.ERROR in _NOTIFY_ACTIONS

    def test_notify_actions_contains_results(self):
        assert ActionType.RESULT in _NOTIFY_ACTIONS

    def test_notify_actions_does_not_contain_text(self):
        assert ActionType.TEXT not in _NOTIFY_ACTIONS
        assert ActionType.TEXT_DELTA not in _NOTIFY_ACTIONS
        assert ActionType.THINKING not in _NOTIFY_ACTIONS
