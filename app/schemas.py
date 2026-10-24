from typing import Literal

from pydantic import BaseModel, Field


class AttachmentRef(BaseModel):
    """Client echo of a previously uploaded file (returned by POST /v1/agent/files)."""

    name: str = Field(min_length=1, max_length=200)
    # Workspace-relative posix path, e.g. "uploads/report.pdf". Validated
    # server-side against the thread workspace; invalid refs are dropped silently.
    path: str = Field(min_length=1, max_length=300)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    thread_id: str | None = Field(default=None, max_length=200)
    # Keep max_length in sync with settings.upload_max_files_per_thread (default 50).
    attachments: list[AttachmentRef] = Field(default_factory=list, max_length=50)


class UploadResponse(BaseModel):
    name: str  # sanitized (and possibly -N suffixed) name actually saved
    path: str  # "uploads/<name>", workspace-relative
    size: int
    container_path: str  # "/workspace/uploads/<name>"


class SSEEvent(BaseModel):
    type: Literal[
        "start",
        "token",
        "tool_start",
        "tool_end",
        "error",
        "done",
    ]
    data: dict
