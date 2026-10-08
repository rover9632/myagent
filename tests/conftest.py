from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest


class FakeAgent:
    """Implements just enough of the LangGraph interface for AgentService.stream."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.received_config: dict | None = None

    async def astream_events(
        self,
        payload: dict,
        *,
        config: dict | None = None,
        version: str | None = None,
    ) -> AsyncIterator[dict]:
        self.received_config = config
        for event in self.events:
            yield event


class FakeStream:
    """Stand-in for asyncio subprocess streams in _read_limited tests."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class FakeSandbox:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        from app.sandbox import SandboxResult

        self.calls.append(kwargs)
        return SandboxResult(
            exit_code=0,
            stdout="fake-output",
            stderr="",
            duration_ms=1,
        )


@pytest.fixture
def fake_events() -> list[dict[str, Any]]:
    """A representative v2 event stream: tool round-trip plus a streamed token."""
    chunk = type("Chunk", (), {"content": "hello"})()
    return [
        {"event": "on_tool_start", "name": "bash_exec", "data": {"input": {"command": "ls"}}},
        {"event": "on_tool_end", "name": "bash_exec", "data": {"output": "ok"}},
        {"event": "on_chat_model_stream", "data": {"chunk": chunk}},
    ]
