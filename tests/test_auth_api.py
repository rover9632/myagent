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


async def register(
    client, username: str = "bobby", password: str = PASSWORD, **extra
) -> httpx.Response:
    return await client.post(
        "/v1/auth/register", json={"username": username, "password": password, **extra}
    )


async def login(client, account: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/v1/auth/login", json={"account": account, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_register_returns_201_with_session(client):
    resp = await register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["token"]) == 43  # secrets.token_urlsafe(32)
    assert body["username"] == "bobby"
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
        {"username": "abc", "password": PASSWORD},  # 3 chars: below new 4-char minimum
        {"username": "1bobby", "password": PASSWORD},  # digit start: must begin with a letter
        {"username": "has space", "password": PASSWORD},
        {"username": "用户", "password": PASSWORD},
        {"username": "bobby", "password": "short"},  # < 8 chars
        {"username": "bobby", "password": "a" * 73},  # > 72 chars
        {"username": "bobby", "password": "密" * 25},  # 25 chars but 75 UTF-8 bytes
        {"username": "bobby", "password": PASSWORD, "email": "nope"},  # invalid email
        {"username": "bobby", "password": PASSWORD, "phone": "12345"},  # invalid phone
    ],
)
async def test_register_validation_422(client, payload):
    resp = await client.post("/v1/auth/register", json=payload)
    assert resp.status_code == 422


async def test_register_with_email_and_phone(client):
    resp = await register(
        client, "carol", PASSWORD, email="Carol@Example.com", phone="13800138000"
    )
    assert resp.status_code == 201
    store = app.state.user_store
    # normalized before persistence: lowercase email, E.164 phone
    assert "carol@example.com" in store.emails
    assert "+8613800138000" in store.phones


async def test_register_duplicate_email_409(client):
    assert (await register(client, "carol", PASSWORD, email="carol@example.com")).status_code == 201
    # mixed case collapses onto the stored lowercase email
    resp = await register(client, "caroline", PASSWORD, email="CAROL@example.com")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "email already exists"


async def test_register_duplicate_phone_409(client):
    assert (await register(client, "carol", PASSWORD, phone="13800138000")).status_code == 201
    # E.164 canonicalization converges different input spellings
    resp = await register(client, "caroline", PASSWORD, phone="+86 138-0013-8000")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "phone already exists"


async def test_login_issues_fresh_token(client):
    first = (await register(client)).json()["token"]
    resp = await login(client, "bobby")
    assert resp.status_code == 200
    second = resp.json()["token"]
    assert second != first  # new token every login (no fixation)
    # Both tokens are live sessions.
    assert (await client.get("/v1/auth/me", headers=bearer(first))).status_code == 200
    assert (await client.get("/v1/auth/me", headers=bearer(second))).status_code == 200


async def test_login_case_insensitive_username(client):
    await register(client, "bobby")
    resp = await login(client, "BOBBY")
    assert resp.status_code == 200
    assert resp.json()["username"] == "bobby"  # canonical name, not the login spelling


async def test_login_via_email_mixed_case(client):
    await register(client, "carol", PASSWORD, email="carol@example.com")
    resp = await login(client, "CAROL@example.com")
    assert resp.status_code == 200
    assert resp.json()["username"] == "carol"


@pytest.mark.parametrize(
    "account",
    [
        "13800138000",
        "+8613800138000",
        "138 0013 8000",
        "+86-138-0013-8000",
    ],
)
async def test_login_via_phone_forms(client, account):
    await register(client, "carol", PASSWORD, phone="13800138000")
    resp = await login(client, account)
    assert resp.status_code == 200
    assert resp.json()["username"] == "carol"


async def test_login_legacy_digit_username(client):
    # pre-existing rows may violate the new registration regex; the username
    # branch must still authenticate them (falls back when phone parsing fails)
    store = app.state.user_store
    await store.create_user("0123", PASSWORD)
    resp = await login(client, "0123")
    assert resp.status_code == 200
    assert resp.json()["username"] == "0123"


async def test_login_failures_401_identical_detail(client):
    await register(client, "bobby")
    wrong_pw = await login(client, "bobby", "wrongpassword")
    unknown = await login(client, "nobody")
    malformed = await login(client, "12abc!!")  # phone-ish junk must 401, never 422/500
    for resp in (wrong_pw, unknown, malformed):
        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid username or password"
        assert resp.headers.get("www-authenticate") == "Bearer"


async def test_login_over_72_byte_password_is_401_not_500(client):
    await register(client, "bobby")
    resp = await login(client, "bobby", "x" * 100)
    assert resp.status_code == 401


async def test_login_records_last_login_at_and_ip(client):
    await register(client, "bobby")
    uid = app.state.user_store.users["bobby"][0]
    resp = await client.post(
        "/v1/auth/login",
        json={"account": "bobby", "password": PASSWORD},
        headers={"x-forwarded-for": "203.0.113.7, 198.51.100.9"},
    )
    assert resp.status_code == 200
    at, ip = app.state.user_store.logins[uid]
    assert ip == "203.0.113.7"  # first entry of the forwarded chain
    assert (datetime.now(UTC) - at).total_seconds() < 60


async def test_login_ip_invalid_xff_degrades(client):
    await register(client, "bobby")
    uid = app.state.user_store.users["bobby"][0]
    # junk entries are skipped, the first parseable one wins
    await client.post(
        "/v1/auth/login",
        json={"account": "bobby", "password": PASSWORD},
        headers={"x-forwarded-for": "evil, 198.51.100.9"},
    )
    assert app.state.user_store.logins[uid][1] == "198.51.100.9"
    # fully bogus header falls back to the socket peer (ASGITransport = 127.0.0.1)
    await client.post(
        "/v1/auth/login",
        json={"account": "bobby", "password": PASSWORD},
        headers={"x-forwarded-for": "evil, bogus"},
    )
    assert app.state.user_store.logins[uid][1] == "127.0.0.1"


async def test_failed_login_records_nothing(client):
    await register(client, "bobby")
    await login(client, "bobby", "wrongpassword")
    await login(client, "nobody")
    assert app.state.user_store.logins == {}


async def test_register_auto_login_does_not_record(client):
    # last_login_* is a login-time audit trail; the register convenience
    # token intentionally does not touch it.
    await register(client, "bobby")
    assert app.state.user_store.logins == {}


async def test_me_requires_valid_session(client):
    token = (await register(client)).json()["token"]
    ok = await client.get("/v1/auth/me", headers=bearer(token))
    assert ok.status_code == 200
    assert ok.json() == {"username": "bobby"}

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
    saved = app.state.sandbox.workspace_for("bobby", "t-up") / "uploads" / "notes.txt"
    assert saved.read_bytes() == b"marker line"


async def test_cross_user_file_isolation(client):
    alice = (await register(client, "alice")).json()["token"]
    bobby = (await register(client, "bobby")).json()["token"]

    resp = await client.post(
        "/v1/agent/files",
        files={"file": ("secret.txt", b"alice-only", "text/plain")},
        data={"thread_id": "t1"},
        headers=bearer(alice),
    )
    assert resp.status_code == 200

    # Same thread_id, different user: bobby sees an empty listing and alice's
    # file lives under her own two-level namespace only.
    listing = await client.get(
        "/v1/agent/files", params={"thread_id": "t1"}, headers=bearer(bobby)
    )
    assert listing.json() == {"files": []}
    assert (app.state.sandbox.workspace_for("alice", "t1") / "uploads" / "secret.txt").exists()
    assert not (app.state.sandbox.workspace_for("bobby", "t1") / "uploads" / "secret.txt").exists()


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
