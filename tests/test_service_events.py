from __future__ import annotations

import pytest
from conftest import FakeAgent

from app.agent.service import AgentService, _extract_text, _truncate_value
from app.context import get_thread_id


async def test_stream_event_sequence(fake_events):
    service = AgentService(FakeAgent(fake_events))
    out = [event async for event in service.stream(thread_id="t1", message="hi")]

    assert [event.type for event in out] == [
        "start",
        "tool_start",
        "tool_end",
        "token",
        "done",
    ]
    assert out[0].data["thread_id"] == "t1"
    assert out[1].data["tool"] == "bash_exec"
    assert out[3].data["text"] == "hello"


async def test_stream_forwards_thread_id_to_config(fake_events):
    agent = FakeAgent(fake_events)
    service = AgentService(agent)
    _ = [event async for event in service.stream(thread_id="t42", message="hi")]

    assert agent.received_config == {"configurable": {"thread_id": "t42"}}


async def test_stream_error_event_on_chain_error():
    events = [{"event": "on_chain_error", "data": {"error": RuntimeError("boom")}}]
    service = AgentService(FakeAgent(events))
    out = [event async for event in service.stream(thread_id="t1", message="hi")]

    assert [event.type for event in out] == ["start", "error"]
    assert "boom" in out[1].data["message"]


async def test_unknown_tool_events_are_ignored():
    events = [{"event": "on_tool_start", "name": "internal_thing", "data": {}}]
    service = AgentService(FakeAgent(events))
    out = [event async for event in service.stream(thread_id="t1", message="hi")]

    assert [event.type for event in out] == ["start", "done"]


async def test_thread_contextvar_is_reset_after_stream():
    service = AgentService(FakeAgent([]))
    _ = [event async for event in service.stream(thread_id="t1", message="hi")]

    with pytest.raises(RuntimeError):
        get_thread_id()


def test_extract_text_handles_blocks_and_plain():
    assert _extract_text("plain") == "plain"
    assert _extract_text([{"type": "text", "text": "a"}, "b"]) == "ab"
    assert _extract_text(123) == ""


def test_truncate_value_bounds():
    assert _truncate_value("x" * 30, limit=10) == "x" * 10 + "...[truncated]"
    # depth=2: values at depth 1 recurse once more, at depth 0 they collapse to "..."
    deep = _truncate_value({"a": {"b": {"c": {"d": "deep"}}}}, depth=2)
    assert deep["a"]["b"] == "..."
