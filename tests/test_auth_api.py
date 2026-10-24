from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import FakeAgent, FakeSandbox, FakeUserStore

from app.agent.service import AgentService
from app.main import app

PASSWORD = "password123"


@pytest.fixture
def client(tmp_path):
    # ASGITransport does not run the lifespan, so wire state manually.
    # NO dependency overrides: auth-flow tests exercise the real require_user.
    app.state.user_store = FakeUserStore()
    app.state.agent_service = AgentService(FakeAgent([]))
    app.state.sandbox = FakeSandbox(tmp_path)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def register(client, username: str = "bob", password: str = PASSWORD) -> httpx.Response:
    return await client.post(
        "/v1/auth/register", json={"username": username, "password": password}
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_register_returns_201_with_session(client):
    resp = await register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["token"]) == 43  # secrets.token_urlsafe(32)
    assert body["username"] == "bob"
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)


async def test_register_duplicate_username_409(client):
    assert (await register(client)).status_code == 201
    resp = await register(client)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "username already exists"


async def test_register_case_insensitive_duplicate_409(client):
    assert (await register(client, "alice")).status_code == 201
    assert (await register(client, "Alice")).status_code == 409
    assert (await register(client, "ALICE")).status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab", "password": PASSWORD},  # too short
        {"username": "has space", "password": PASSWORD},
        {"username": "用户", "password": PASSWORD},
        {"username": "bob", "password": "short"},  # < 8 chars
        {"username": "bob", "password": "a" * 73},  # > 72 chars
        {"username": "bob", "password": "密" * 25},  # 25 chars but 75 UTF-8 bytes
    ],
)
async def test_register_validation_422(client, payload):
    resp = await client.post("/v1/auth/register", json=payload)
    assert resp.status_code == 422


async def test_login_issues_fresh_token(client):
    first = (await register(client)).json()["token"]
    resp = await client.post("/v1/auth/login", json={"username": "bob", "password": PASSWORD})
    assert resp.status_code == 200
    second = resp.json()["token"]
    assert second != first  # new token every login (no fixation)
    # Both tokens are live sessions.
    assert (await client.get("/v1/auth/me", headers=bearer(first))).status_code == 200
    assert (await client.get("/v1/auth/me", headers=bearer(second))).status_code == 200


async def test_login_case_insensitive_username(client):
    await register(client, "bob")
    resp = await client.post("/v1/auth/login", json={"username": "BOB", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"  # canonical name, not the login spelling


async def test_login_failures_401_identical_detail(client):
    await register(client, "bob")
    wrong_pw = await client.post(
        "/v1/auth/login", json={"username": "bob", "password": "wrongpassword"}
    )
    unknown = await client.post(
        "/v1/auth/login", json={"username": "nobody", "password": PASSWORD}
    )
    for resp in (wrong_pw, unknown):
        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid username or password"
        assert resp.headers.get("www-authenticate") == "Bearer"


async def test_login_over_72_byte_password_is_401_not_500(client):
    await register(client, "bob")
    resp = await client.post("/v1/auth/login", json={"username": "bob", "password": "x" * 100})
    assert resp.status_code == 401


async def test_me_requires_valid_session(client):
    token = (await register(client)).json()["token"]
    ok = await client.get("/v1/auth/me", headers=bearer(token))
    assert ok.status_code == 200
    assert ok.json() == {"username": "bob"}

    for headers in ({}, bearer("garbage"), {"Authorization": f"token {token}"}):
        resp = await client.get("/v1/auth/me", headers=headers)
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"


async def test_me_rejects_expired_session(client):
    store = app.state.user_store
    token = (await register(client)).json()["token"]
    user_id, _expires = store.sessions[token]
    store.sessions[token] = (user_id, datetime.now(UTC) - timedelta(seconds=1))
    resp = await client.get("/v1/auth/me", headers=bearer(token))
    assert resp.status_code == 401
    assert token not in store.sessions  # expired entry purged on read


async def test_logout_revokes_token(client):
    token = (await register(client)).json()["token"]
    resp = await client.post("/v1/auth/logout", headers=bearer(token))
    assert resp.status_code == 204
    assert resp.content == b""
    assert (await client.get("/v1/auth/me", headers=bearer(token))).status_code == 401
    # Second logout with the dead token: 401, not another 204.
    assert (await client.post("/v1/auth/logout", headers=bearer(token))).status_code == 401


async def test_logout_requires_session(client):
    assert (await client.post("/v1/auth/logout")).status_code == 401


async def test_full_flow_chat_stream_with_session(client):
    token = (await register(client)).json()["token"]
    async with client.stream(
        "POST",
        "/v1/agent/chat/stream",
        json={"message": "hi", "thread_id": "t1"},
        headers=bearer(token),
    ) as resp:
        assert resp.status_code == 200
        body = "".join([chunk async for chunk in resp.aiter_text()])
    assert "event: start" in body
    assert "event: done" in body


async def test_full_flow_upload_with_session(client):
    token = (await register(client)).json()["token"]
    resp = await client.post(
        "/v1/agent/files",
        files={"file": ("notes.txt", b"marker line", "text/plain")},
        data={"thread_id": "t-up"},
        headers=bearer(token),
    )
    assert resp.status_code == 200
    saved = app.state.sandbox.workspace_for("bob", "t-up") / "uploads" / "notes.txt"
    assert saved.read_bytes() == b"marker line"


async def test_cross_user_file_isolation(client):
    alice = (await register(client, "alice")).json()["token"]
    bob = (await register(client, "bob")).json()["token"]

    resp = await client.post(
        "/v1/agent/files",
        files={"file": ("secret.txt", b"alice-only", "text/plain")},
        data={"thread_id": "t1"},
        headers=bearer(alice),
    )
    assert resp.status_code == 200

    # Same thread_id, different user: bob sees an empty listing and alice's
    # file lives under her own two-level namespace only.
    listing = await client.get("/v1/agent/files", params={"thread_id": "t1"}, headers=bearer(bob))
    assert listing.json() == {"files": []}
    assert (app.state.sandbox.workspace_for("alice", "t1") / "uploads" / "secret.txt").exists()
    assert not (app.state.sandbox.workspace_for("bob", "t1") / "uploads" / "secret.txt").exists()


async def test_agent_endpoints_reject_anonymous(client):
    stream = await client.post("/v1/agent/chat/stream", json={"message": "hi"})
    upload = await client.post(
        "/v1/agent/files",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"thread_id": "t1"},
    )
    listing = await client.get("/v1/agent/files", params={"thread_id": "t1"})
    for resp in (stream, upload, listing):
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"
