from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


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


class RegisterRequest(BaseModel):
    # Same grammar as app.user_store.USERNAME_RE — directory-safe by construction.
    username: str = Field(pattern=r"^[a-zA-Z0-9_-]{3,32}$")
    password: str = Field(min_length=8, max_length=72)

    @model_validator(mode="after")
    def _password_within_bcrypt_limit(self) -> Self:
        # max_length counts chars; bcrypt silently truncates (bcrypt 5 raises)
        # past 72 UTF-8 bytes — reject at the API edge instead.
        if len(self.password.encode("utf-8")) > 72:
            raise ValueError("password must not exceed 72 bytes")
        return self


class LoginRequest(BaseModel):
    # Lenient caps: login input is only compared, never stored. Over-72-byte
    # passwords simply fail authentication (401), never a validation error.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    token: str
    username: str
    expires_at: datetime


class MeResponse(BaseModel):
    username: str
