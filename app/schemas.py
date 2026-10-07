from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    thread_id: str | None = Field(default=None, max_length=200)


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
