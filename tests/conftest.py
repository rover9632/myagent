from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.auth import require_user
from app.user_store import (
    DuplicateEmail,
    DuplicatePhone,
    DuplicateUsername,
    MeData,
    User,
    classify_account,
    ip_str,
)


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
    semantics (case-insensitive names, email/phone identifier forms, fresh
    token per session, expiry) match the real store.
    """

    def __init__(self, session_ttl_days: int = 30) -> None:
        self.users: dict[str, tuple[UUID, str]] = {}  # username -> (id, password)
        self.emails: dict[str, UUID] = {}  # lowercased email -> user id
        self.phones: dict[str, UUID] = {}  # E.164 phone -> user id
        self.sessions: dict[str, tuple[UUID, datetime]] = {}  # token -> (user_id, expires_at)
        self.logins: dict[UUID, tuple[datetime, str | None]] = {}  # user_id -> (at, ip)
        # Profile-center backing stores: per-user account row (display source)
        # and user_profiles rows (absent key == no row, exactly like the DB).
        self.accounts: dict[UUID, dict[str, Any]] = {}
        self.profile_rows: dict[UUID, dict[str, Any]] = {}
        self.session_ttl_days = session_ttl_days

    async def create_user(
        self,
        username: str,
        password: str,
        *,
        email: str | None = None,
        phone: str | None = None,
    ) -> User:
        # email/phone arrive already normalized (lowercase / E.164) — the
        # RegisterRequest validators are shared with the real store.
        if username.lower() in {u.lower() for u in self.users}:
            raise DuplicateUsername(username)
        if email is not None and email in self.emails:
            raise DuplicateEmail(username)
        if phone is not None and phone in self.phones:
            raise DuplicatePhone(username)
        uid = uuid4()
        self.users[username] = (uid, password)
        if email is not None:
            self.emails[email] = uid
        if phone is not None:
            self.phones[phone] = uid
        self.accounts[uid] = {
            "email": email,
            "phone": phone,
            "email_verified_at": None,  # register never verifies anything
            "phone_verified_at": None,
            "status": "active",
            "created_at": datetime.now(UTC),
            "plain": password,
        }
        return User(id=uid, username=username)

    async def authenticate(self, account: str, password: str) -> User | None:
        # Mirrors the real store: classify, then username > email > phone
        # priority; username match stays case-insensitive, canonical name back.
        username_part, email_part, phone_part = classify_account(account)
        user_id: UUID | None = None
        name: str | None = None
        pw: str | None = None
        for key, (uid, plain) in self.users.items():
            if key.lower() == username_part.lower():
                name, user_id, pw = key, uid, plain
                break
        if user_id is None and email_part is not None:
            user_id = self.emails.get(email_part)
        if user_id is None and phone_part is not None:
            user_id = self.phones.get(phone_part)
        if user_id is None:
            return None
        if name is None or pw is None:  # matched by email/phone: recover the canonical username
            for key, (uid, plain) in self.users.items():
                if uid == user_id:
                    name, pw = key, plain
                    break
        if name is None or pw is None:
            return None
        return User(id=user_id, username=name) if pw == password else None

    async def touch_login(self, user_id: UUID, ip: str | None) -> None:
        # Mirrors UserStore.touch_login: last_login_at + last_login_ip audit row.
        self.logins[user_id] = (datetime.now(UTC), ip)

    async def create_session(self, user_id: UUID) -> tuple[str, datetime]:
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

    async def revoke_other_sessions(self, user_id: UUID, keep_token: str | None) -> int:
        removed = 0
        for token, (uid, _expires) in list(self.sessions.items()):
            if uid == user_id and token != keep_token:
                del self.sessions[token]
                removed += 1
        return removed

    def _username_for(self, user_id: UUID) -> str | None:
        for key, (uid, _pw) in self.users.items():
            if uid == user_id:
                return key
        return None

    async def get_me(self, user_id: UUID) -> MeData | None:
        username = self._username_for(user_id)
        acc = self.accounts.get(user_id)
        if username is None or acc is None:
            return None
        prof = self.profile_rows.get(user_id)
        login = self.logins.get(user_id)
        return MeData(
            id=user_id,
            username=username,
            email=acc["email"],
            phone=acc["phone"],
            status=acc["status"],
            email_verified_at=acc["email_verified_at"],
            phone_verified_at=acc["phone_verified_at"],
            last_login_at=login[0] if login else None,
            # Same read-edge normalization as the real store: tests can seed
            # ipaddress objects (what psycopg actually returns for INET).
            last_login_ip=ip_str(login[1]) if login else None,
            created_at=acc["created_at"],
            display_name=prof.get("display_name") if prof else None,
            avatar_url=prof.get("avatar_url") if prof else None,
            bio=prof.get("bio") if prof else None,
            locale=prof.get("locale", "zh-CN") if prof else "zh-CN",
            timezone=prof.get("timezone", "Asia/Shanghai") if prof else "Asia/Shanghai",
        )

    async def update_me(self, user_id: UUID, changes: dict) -> None:
        # Mirrors UserStore.update_me semantics: key present == intended write,
        # *_verified_at resets only on an actual value change, self-owned values
        # never collide, and a collision aborts the WHOLE update (the real store
        # does it in one transaction) — so conflicts are detected before any
        # mutation happens.
        if not changes:
            return
        acc = self.accounts.get(user_id)
        if acc is None:
            return
        half_specs = (
            ("email", "email_verified_at", self.emails, DuplicateEmail),
            ("phone", "phone_verified_at", self.phones, DuplicatePhone),
        )
        plan = []
        for field, verified_key, index, exc_cls in half_specs:
            if field not in changes or changes[field] == acc[field]:
                continue
            new = changes[field]
            if new is not None:
                other = index.get(new)
                if other is not None and other != user_id:
                    raise exc_cls(str(user_id))
            plan.append((field, verified_key, index, new))
        for field, verified_key, index, new in plan:
            old = acc[field]
            if old is not None:
                index.pop(old, None)
            if new is not None:
                index[new] = user_id
            acc[field] = new
            acc[verified_key] = None
        profile_keys = ("display_name", "avatar_url", "bio", "locale", "timezone")
        provided = {k: changes[k] for k in profile_keys if k in changes}
        if provided:
            # Lazy row creation with the same defaults the ORM declares.
            row = self.profile_rows.setdefault(
                user_id, {"locale": "zh-CN", "timezone": "Asia/Shanghai"}
            )
            row.update(provided)

    async def change_password(
        self, user_id: UUID, current_password: str, new_password: str
    ) -> bool:
        acc = self.accounts.get(user_id)
        if acc is None or acc["plain"] != current_password:
            return False
        acc["plain"] = new_password
        username = self._username_for(user_id)
        if username is not None:
            self.users[username] = (user_id, new_password)
        return True


@contextmanager
def logged_in(app, username: str = "tester"):
    """Wire a FakeUserStore + require_user override; yields the store.

    For agent-endpoint tests that don't exercise the real auth path. Auth-flow
    tests (test_auth_api.py) skip the override and set app.state.user_store only.
    """
    app.state.user_store = FakeUserStore()
    app.dependency_overrides[require_user] = lambda: User(id=uuid4(), username=username)
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
