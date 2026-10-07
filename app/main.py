from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.agent import AgentService, build_agent
from app.config import get_settings
from app.sandbox import DockerSandbox
from app.schemas import ChatRequest

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sandbox = DockerSandbox(
        image=settings.sandbox_image,
        workspace_root=settings.sandbox_workspace_root,
        default_timeout_seconds=settings.sandbox_default_timeout_seconds,
        max_timeout_seconds=settings.sandbox_max_timeout_seconds,
        memory=settings.sandbox_memory,
        cpus=settings.sandbox_cpus,
        pids_limit=settings.sandbox_pids_limit,
        max_output_bytes=settings.sandbox_max_output_bytes,
    )

    await sandbox.check_available()
    agent = build_agent(settings, sandbox)
    app.state.agent_service = AgentService(agent)
    app.state.sandbox = sandbox
    logger.info("Agent ready: model=%s base_url=%s", settings.llm_model, settings.llm_base_url)
    yield


app = FastAPI(
    title="LangChain Agent MVP",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "model": settings.llm_model,
        "llm_base_url": settings.llm_base_url,
        "sandbox_image": settings.sandbox_image,
    }


@app.post("/v1/agent/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: ChatRequest):
    thread_id = request.thread_id or uuid4().hex
    service: AgentService = app.state.agent_service

    async for item in service.stream(
        thread_id=thread_id,
        message=request.message,
    ):
        event_type = item["type"]
        if event_type == "done":
            yield ServerSentEvent(data=item["data"], event="done")
        else:
            yield ServerSentEvent(data=item["data"], event=event_type)
