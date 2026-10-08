from __future__ import annotations

import httpx
import pytest
from conftest import FakeAgent

from app.agent.service import AgentService
from app.main import app

ENDPOINT = "/v1/agent/chat/stream"


@pytest.fixture
def client():
    # ASGITransport does not run the lifespan, so wire just enough state.
    app.state.agent_service = AgentService(FakeAgent([]))
    app.state.sandbox = None
    app.state.api_token = ""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_healthz_stays_open(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    # base_url of the LLM must not leak to unauthenticated probes.
    assert "llm_base_url" not in resp.json()


async def test_stream_sse_event_framing(client, fake_events):
    app.state.agent_service = AgentService(FakeAgent(fake_events))

    async with client.stream(
        "POST", ENDPOINT, json={"message": "hi", "thread_id": "t1"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = [line async for line in resp.aiter_lines()]

    events = [line.removeprefix("event: ").strip() for line in lines if line.startswith("event:")]
    assert events == ["start", "tool_start", "tool_end", "token", "done"]


async def test_empty_message_rejected(client):
    resp = await client.post(ENDPOINT, json={"message": ""})
    assert resp.status_code == 422


async def test_auth_rejects_when_token_configured(client):
    app.state.api_token = "s3cret"

    missing = await client.post(ENDPOINT, json={"message": "hi"})
    wrong = await client.post(
        ENDPOINT, json={"message": "hi"}, headers={"Authorization": "Bearer nope"}
    )
    basic_scheme = await client.post(
        ENDPOINT, json={"message": "hi"}, headers={"Authorization": "token s3cret"}
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert basic_scheme.status_code == 401
    assert missing.headers.get("www-authenticate") == "Bearer"


async def test_auth_accepts_correct_bearer_token(client):
    app.state.api_token = "s3cret"
    resp = await client.post(
        ENDPOINT, json={"message": "hi"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert resp.status_code == 200
