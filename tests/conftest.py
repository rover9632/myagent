from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.auth import require_user
from app.user_store import DuplicateUsername, User


class FakeAgent:
    """Implements just enough of the LangGraph interface for AgentService.stream."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.received_config: dict | None = None
        self.received_payload: dict | None = None

    async def astream_events(
        self,
        payload: dict,
        *,
        config: dict | None = None,
        version: str | None = None,
    ) -> AsyncIterator[dict]:
        self.received_config = config
        self.received_payload = payload
        for event in self.events:
            yield event


class FakeStream:
    """Stand-in for asyncio subprocess streams in _read_limited tests."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class FakeSandbox:
    def __init__(self, workspace_root: Any = None) -> None:
        self.calls: list[dict] = []
        self.workspace_root = Path(workspace_root) if workspace_root is not None else None

    def workspace_for(self, user: str, thread_id: str) -> Path:
        """Mirror DockerSandbox.workspace_for (same two-level sanitization)."""
        from app.sandbox.docker import DockerSandbox

        assert self.workspace_root is not None, "FakeSandbox built without workspace_root"
        path = (
            self.workspace_root
            / DockerSandbox._safe_thread_id(user)
            / DockerSandbox._safe_thread_id(thread_id)
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def run(self, **kwargs):
        from app.sandbox import SandboxResult

        self.calls.append(kwargs)
        return SandboxResult(
            exit_code=0,
            stdout="fake-output",
            stderr="",
            duration_ms=1,
        )


class FakeUserStore:
    """In-memory mirror of app.user_store.UserStore's contract.

    Plaintext passwords on purpose: bcrypt correctness is covered by
    test_auth_units.py, SQL by the real-backend smoke. Method signatures and
    semantics (case-insensitive names, fresh token per session, expiry) match
    the real store.
    """

    def __init__(self, session_ttl_days: int = 30) -> None:
        self.users: dict[str, tuple[int, str]] = {}  # username -> (id, password)
        self.sessions: dict[str, tuple[int, datetime]] = {}  # token -> (user_id, expires_at)
        self._next_id = 1
        self.session_ttl_days = session_ttl_days

    async def bootstrap(self) -> None:  # no-op: nothing to create in memory
        pass

    async def create_user(self, username: str, password: str) -> User:
        if username.lower() in {u.lower() for u in self.users}:
            raise DuplicateUsername(username)
        uid = self._next_id
        self._next_id += 1
        self.users[username] = (uid, password)
        return User(id=uid, username=username)

    async def authenticate(self, username: str, password: str) -> User | None:
        # Mirrors the real store's lower(username) lookup: case-insensitive
        # match, canonical username returned.
        for name, (uid, pw) in self.users.items():
            if name.lower() == username.lower():
                return User(id=uid, username=name) if pw == password else None
        return None

    async def create_session(self, user_id: int) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)  # real generator: exercises the same flow
        expires = datetime.now(UTC) + timedelta(days=self.session_ttl_days)
        self.sessions[token] = (user_id, expires)
        return token, expires

    async def user_for_token(self, token: str) -> User | None:
        entry = self.sessions.get(token)
        if entry is None:
            return None
        user_id, expires = entry
        if expires <= datetime.now(UTC):
            del self.sessions[token]
            return None
        for username, (uid, _pw) in self.users.items():
            if uid == user_id:
                return User(id=uid, username=username)
        return None

    async def revoke_token(self, token: str) -> None:
        self.sessions.pop(token, None)


@contextmanager
def logged_in(app, username: str = "tester"):
    """Wire a FakeUserStore + require_user override; yields the store.

    For agent-endpoint tests that don't exercise the real auth path. Auth-flow
    tests (test_auth_api.py) skip the override and set app.state.user_store only.
    """
    app.state.user_store = FakeUserStore()
    app.dependency_overrides[require_user] = lambda: User(id=1, username=username)
    try:
        yield app.state.user_store
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def fake_events() -> list[dict[str, Any]]:
    """A representative v2 event stream: tool round-trip plus a streamed token."""
    chunk = type("Chunk", (), {"content": "hello"})()
    return [
        {"event": "on_tool_start", "name": "bash_exec", "data": {"input": {"command": "ls"}}},
        {"event": "on_tool_end", "name": "bash_exec", "data": {"output": "ok"}},
        {"event": "on_chat_model_stream", "data": {"chunk": chunk}},
    ]
