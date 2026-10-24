from __future__ import annotations

import httpx
import pytest
from conftest import FakeAgent, logged_in

from app.agent.service import AgentService
from app.main import app

ENDPOINT = "/v1/agent/chat/stream"


@pytest.fixture
def client():
    # ASGITransport does not run the lifespan, so wire just enough state.
    app.state.agent_service = AgentService(FakeAgent([]))
    app.state.sandbox = None
    with logged_in(app, username="tester"):
        transport = httpx.ASGITransport(app=app)
        yield httpx.AsyncClient(transport=transport, base_url="http://testserver")


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


async def test_agent_endpoints_require_session(client):
    app.dependency_overrides.clear()  # exercise the REAL require_user path

    for headers in (
        {},  # missing entirely
        {"Authorization": "Bearer nope"},  # unknown token
        {"Authorization": "token s3cret"},  # wrong scheme
    ):
        stream = await client.post(ENDPOINT, json={"message": "hi"}, headers=headers)
        upload = await client.post(
            "/v1/agent/files",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            data={"thread_id": "t1"},
            headers=headers,
        )
        listing = await client.get("/v1/agent/files", params={"thread_id": "t1"}, headers=headers)
        for resp in (stream, upload, listing):
            assert resp.status_code == 401
            assert resp.headers.get("www-authenticate") == "Bearer"


async def test_stream_config_is_namespaced_per_user(client, fake_events):
    agent = FakeAgent(fake_events)
    app.state.agent_service = AgentService(agent)

    resp = await client.post(ENDPOINT, json={"message": "hi", "thread_id": "t1"})
    assert resp.status_code == 200
    # Checkpointer key is namespaced with the logged-in username, while SSE
    # events keep echoing the client-facing thread_id.
    assert agent.received_config == {"configurable": {"thread_id": "tester:t1"}}
