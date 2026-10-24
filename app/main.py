from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent import AgentService, build_agent
from app.auth import User, require_user
from app.auth_api import router as auth_router
from app.config import get_settings
from app.sandbox import DockerSandbox
from app.schemas import ChatRequest, UploadResponse
from app.uploads import (
    UploadRejected,
    build_attachment_note,
    list_uploads,
    parse_allowed_extensions,
    save_upload,
)
from app.user_store import UserStore

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def _workspace_cleanup_loop(sandbox: DockerSandbox, interval_seconds: int = 3600) -> None:
    """Periodically delete stale thread workspaces so disk usage stays bounded."""
    while True:
        try:
            removed = await asyncio.to_thread(sandbox.cleanup_expired_workspaces)
            if removed:
                logger.info("Workspace cleanup removed %d expired directories", removed)
        except Exception:
            logger.exception("Workspace cleanup failed")
        await asyncio.sleep(interval_seconds)


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
        workspace_ttl_days=settings.sandbox_workspace_ttl_days,
    )
    await sandbox.check_available()  # fail before touching PG when docker is broken

    pool = AsyncConnectionPool(
        conninfo=settings.pg_uri,  # plain libpq URI: postgresql://user:pass@host:port/db
        min_size=settings.pg_pool_min_size,
        max_size=settings.pg_pool_max_size,
        open=False,  # never open implicitly in __init__
        check=AsyncConnectionPool.check_connection,  # revive/replace dead conns
        kwargs={
            "autocommit": True,  # required by AsyncPostgresSaver for pools
            "prepare_threshold": None,  # required pattern; also pgbouncer-safe
            "row_factory": dict_row,  # required by the saver; handy for UserStore
        },
    )
    try:
        await pool.open(wait=True)  # fail fast on bad credentials/host
    except Exception as exc:
        raise RuntimeError(f"Postgres unavailable at startup: {exc}") from exc

    user_store = UserStore(pool, session_ttl_days=settings.session_ttl_days)
    await user_store.bootstrap()  # CREATE TABLE IF NOT EXISTS users/sessions

    checkpointer = AsyncPostgresSaver(pool)  # ctor needs a running loop → here, not import time
    await checkpointer.setup()  # idempotent checkpoint-table migrations

    agent = build_agent(settings, sandbox, checkpointer)
    app.state.pool = pool
    app.state.user_store = user_store
    app.state.agent_service = AgentService(agent)
    app.state.sandbox = sandbox
    logger.info("Agent ready: model=%s base_url=%s", settings.llm_model, settings.llm_base_url)

    cleanup_task = asyncio.create_task(_workspace_cleanup_loop(sandbox))
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        await pool.close()


app = FastAPI(
    title="LangChain Agent MVP",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(auth_router)


@app.middleware("http")
async def reject_oversized_upload(request: Request, call_next):
    """Early-reject giant uploads BEFORE Starlette spools the whole body to /tmp.

    A dependency can't do this: FastAPI awaits request.form() before solving
    dependencies, and form parsing has no size cap for file parts. The exact
    limit is still enforced chunk-by-chunk in app.uploads._copy_capped for
    chunked requests that omit Content-Length.
    """
    if request.method == "POST" and request.url.path == "/v1/agent/files":
        length = request.headers.get("content-length")
        # +1MB slack for multipart framing overhead.
        if length and length.isdigit() and int(length) > settings.upload_max_bytes + 1024 * 1024:
            return JSONResponse({"detail": "upload exceeds size limit"}, status_code=413)
    return await call_next(request)


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "model": settings.llm_model,
        "sandbox_image": settings.sandbox_image,
    }


@app.post("/v1/agent/files", response_model=UploadResponse)
async def upload_agent_file(
    file: Annotated[UploadFile, File()],
    thread_id: Annotated[str, Form(min_length=1, max_length=200)],
    user: Annotated[User, Depends(require_user)],
):
    sandbox = getattr(app.state, "sandbox", None)
    if sandbox is None:
        raise HTTPException(status_code=503, detail="sandbox not ready")
    workspace = sandbox.workspace_for(user.username, thread_id)  # idempotent mkdir
    try:
        return await save_upload(
            spool=file.file,  # raw spool; read in-thread, never fully in RAM
            original_filename=file.filename,  # untrusted -> sanitized inside
            workspace=workspace,
            max_bytes=settings.upload_max_bytes,
            allowed=parse_allowed_extensions(settings.upload_allowed_extensions),
            max_files=settings.upload_max_files_per_thread,
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    finally:
        await file.close()


@app.get("/v1/agent/files")
async def list_agent_files(
    thread_id: Annotated[str, Query(min_length=1, max_length=200)],
    user: Annotated[User, Depends(require_user)],
):
    sandbox = getattr(app.state, "sandbox", None)
    if sandbox is None:
        raise HTTPException(status_code=503, detail="sandbox not ready")
    workspace = sandbox.workspace_for(user.username, thread_id)
    files = await asyncio.to_thread(list_uploads, workspace)
    return {"files": files}


@app.post("/v1/agent/chat/stream", response_class=EventSourceResponse)
async def chat_stream(request: ChatRequest, user: Annotated[User, Depends(require_user)]):
    thread_id = request.thread_id or uuid4().hex
    service: AgentService = app.state.agent_service

    # Attachment manifest is injected only when the client echoes attachments;
    # the directory scan then validates/augments them (see app.uploads).
    note = None
    sandbox = getattr(app.state, "sandbox", None)
    if request.attachments and sandbox is not None:
        workspace = sandbox.workspace_for(user.username, thread_id)
        note = await asyncio.to_thread(build_attachment_note, workspace, request.attachments)

    async for event in service.stream(
        username=user.username,
        thread_id=thread_id,
        message=request.message,
        attachment_note=note,
    ):
        yield ServerSentEvent(data=event.data, event=event.type)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
