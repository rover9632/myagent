from __future__ import annotations

import ipaddress
from datetime import UTC, datetime

import httpx
import pytest
from conftest import FakeAgent, FakeSandbox, FakeUserStore

from app.agent.service import AgentService
from app.main import app

PASSWORD = "password123"
NEW_PASSWORD = "newsecret789"


@pytest.fixture
def client(tmp_path):
    # ASGITransport does not run the lifespan, so wire state manually.
    # NO dependency overrides: /v1/me tests exercise the real require_user
    # (the logged_in() helper mints an id the store has never seen).
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


async def signup(client, username: str = "bobby", **extra) -> str:
    resp = await register(client, username=username, **extra)
    assert resp.status_code == 201
    return resp.json()["token"]


def store() -> FakeUserStore:
    return app.state.user_store


def uid_of(username: str = "bobby"):
    return store().users[username][0]


# --- GET /v1/me ---------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer nope"},
        {"Authorization": "Basic abc123"},
    ],
)
async def test_get_me_requires_session(client, headers):
    resp = await client.get("/v1/me", headers=headers)
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


async def test_get_me_shape(client):
    token = await signup(client, email="Bob@Example.com", phone="13800138000")
    resp = await client.get("/v1/me", headers=bearer(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "bobby"
    assert body["email"] == "bob@example.com"  # stored lowercase
    assert body["phone"] == "+8613800138000"  # E.164
    assert body["status"] == "active"
    # register never verifies anything — this is the 未验证 badge source
    assert body["email_verified_at"] is None
    assert body["phone_verified_at"] is None
    # no user_profiles row yet: synthesized ORM defaults
    assert body["locale"] == "zh-CN"
    assert body["timezone"] == "Asia/Shanghai"
    assert body["display_name"] is None
    assert body["last_login_at"] is None  # register auto-logins but does not touch_login
    assert datetime.fromisoformat(body["created_at"]) <= datetime.now(UTC)
    assert body["id"] == str(uid_of())
    for secret in ("password_hash", "deleted_at", "attributes"):
        assert secret not in body


async def test_get_me_serializes_inet_objects(client):
    # psycopg reads INET columns back as ipaddress objects (an IPv4 stored via
    # PG often arrives ::ffff:-mapped). Before get_me normalized at the read
    # edge this passed straight into MeProfileResponse and 500'd.
    token = await signup(client)
    uid = uid_of()
    for raw in (
        ipaddress.ip_address("::ffff:127.0.0.1"),
        ipaddress.ip_address("203.0.113.9"),
    ):
        store().logins[uid] = (datetime.now(UTC), raw)  # type: ignore[arg-type]
        resp = await client.get("/v1/me", headers=bearer(token))
        assert resp.status_code == 200
        assert resp.json()["last_login_ip"] == str(raw)


# --- PATCH /v1/me -------------------------------------------------------------


async def test_patch_creates_profile_row_lazily(client):
    token = await signup(client)
    resp = await client.patch("/v1/me", headers=bearer(token), json={"display_name": "小明"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "小明"
    row = store().profile_rows[uid_of()]
    assert row["display_name"] == "小明"
    assert row["locale"] == "zh-CN"  # lazy insert carries the column defaults
    assert row["timezone"] == "Asia/Shanghai"


async def test_patch_email_change_resets_verified(client):
    token = await signup(client, email="bob@example.com")
    store().accounts[uid_of()]["email_verified_at"] = datetime.now(UTC)
    resp = await client.patch("/v1/me", headers=bearer(token), json={"email": "new@example.com"})
    assert resp.status_code == 200
    assert resp.json()["email_verified_at"] is None


async def test_patch_unchanged_email_keeps_verified(client):
    # The web form resubmits every field; an identical (or case-variant, i.e.
    # normalization-equal) email must NOT wipe the verified badge.
    token = await signup(client, email="bob@example.com")
    verified = datetime.now(UTC)
    store().accounts[uid_of()]["email_verified_at"] = verified
    for resubmit in ("bob@example.com", "BOB@EXAMPLE.COM"):
        resp = await client.patch("/v1/me", headers=bearer(token), json={"email": resubmit})
        assert resp.status_code == 200
        assert resp.json()["email"] == "bob@example.com"
        assert resp.json()["email_verified_at"] is not None


async def test_patch_conflict_409_rolls_back_profile(client):
    await signup(client, email="bob@example.com")
    carol = await signup(client, username="carol4", email="carol@example.com")
    resp = await client.patch(
        "/v1/me", headers=bearer(carol), json={"email": "bob@example.com", "bio": "lost"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "email already exists"
    # single transaction: the profile half of the SAME request must not stick
    assert uid_of("carol4") not in store().profile_rows


async def test_patch_own_email_is_not_a_conflict(client):
    token = await signup(client, email="bob@example.com")
    resp = await client.patch("/v1/me", headers=bearer(token), json={"email": "bob@example.com"})
    assert resp.status_code == 200


async def test_patch_blank_clears_contact_fields(client):
    token = await signup(client, email="bob@example.com", phone="13800138000")
    uid = uid_of()
    store().accounts[uid]["email_verified_at"] = datetime.now(UTC)
    store().accounts[uid]["phone_verified_at"] = datetime.now(UTC)
    resp = await client.patch("/v1/me", headers=bearer(token), json={"email": "", "phone": ""})
    assert resp.status_code == 200
    assert resp.json()["email"] is None
    assert resp.json()["phone"] is None
    assert resp.json()["email_verified_at"] is None
    assert resp.json()["phone_verified_at"] is None
    # uniqueness indexes released: the cleared identifiers are claimable again
    assert "bob@example.com" not in store().emails


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email"},
        {"phone": "not-a-phone"},
        {"display_name": "x" * 101},
        {"locale": None},  # NOT NULL columns cannot be cleared
        {"locale": ""},
        {"timezone": "z" * 65},
    ],
)
async def test_patch_validation_422(client, body):
    token = await signup(client)
    resp = await client.patch("/v1/me", headers=bearer(token), json=body)
    assert resp.status_code == 422


async def test_patch_empty_body_is_noop(client):
    token = await signup(client)
    resp = await client.patch("/v1/me", headers=bearer(token), json={})
    assert resp.status_code == 200
    assert uid_of() not in store().profile_rows  # an empty PATCH must not create a row


# --- POST /v1/me/password -----------------------------------------------------


async def test_password_wrong_current_403_keeps_session(client):
    token = await signup(client)
    resp = await client.post(
        "/v1/me/password",
        headers=bearer(token),
        json={"current_password": "wrong", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "current password is incorrect"
    # 403 (not 401): the acting session survives
    assert (await client.get("/v1/me", headers=bearer(token))).status_code == 200


async def test_password_change_flows_through_login(client):
    token = await signup(client)
    resp = await client.post(
        "/v1/me/password",
        headers=bearer(token),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 204
    assert (await login(client, "bobby", PASSWORD)).status_code == 401
    assert (await login(client, "bobby", NEW_PASSWORD)).status_code == 200


async def test_password_change_revokes_other_sessions(client):
    token_a = await signup(client)
    resp_b = await login(client, "bobby", PASSWORD)
    assert resp_b.status_code == 200
    token_b = resp_b.json()["token"]
    resp = await client.post(
        "/v1/me/password",
        headers=bearer(token_a),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 204
    assert (await client.get("/v1/auth/me", headers=bearer(token_b))).status_code == 401
    assert (await client.get("/v1/auth/me", headers=bearer(token_a))).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"current_password": PASSWORD, "new_password": "密" * 25},  # 75 UTF-8 bytes > bcrypt 72
        {"current_password": PASSWORD, "new_password": "short"},
        {"current_password": "", "new_password": NEW_PASSWORD},
    ],
)
async def test_password_validation_422(client, body):
    token = await signup(client)
    resp = await client.post("/v1/me/password", headers=bearer(token), json=body)
    assert resp.status_code == 422


async def test_password_overlong_current_403_not_422(client):
    # current_password is compared, never stored: lenient like login (schema cap
    # 200 chars; over-bcrypt-cliff just fails verification → 403, never 500).
    token = await signup(client)
    resp = await client.post(
        "/v1/me/password",
        headers=bearer(token),
        json={"current_password": "y" * 100, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 403
