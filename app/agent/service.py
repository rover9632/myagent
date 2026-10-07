from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.context import reset_thread_id, set_thread_id


_TOOL_NAMES = {
    "web_search",
    "bash_exec",
    "python_exec",
    "python_run_script",
}


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type in {"text", "output_text"} and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "".join(parts)


def _truncate_value(value: Any, limit: int = 2000, depth: int = 3) -> Any:
    if depth <= 0:
        return "..."
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "...[truncated]"
    if isinstance(value, dict):
        return {str(k): _truncate_value(v, limit, depth - 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_value(v, limit, depth - 1) for v in value[:20]]
    return value


class AgentService:
    def __init__(self, agent) -> None:
        self.agent = agent

    async def stream(
        self,
        *,
        thread_id: str,
        message: str,
    ) -> AsyncIterator[dict]:
        token = set_thread_id(thread_id)
        try:
            yield {
                "type": "start",
                "data": {
                    "thread_id": thread_id,
                },
            }

            config = {
                "configurable": {
                    "thread_id": thread_id,
                }
            }

            try:
                async for event in self.agent.astream_events(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": message,
                            }
                        ]
                    },
                    config=config,
                    version="v2",
                ):
                    event_name = event.get("event")
                    run_name = event.get("name")
                    data = event.get("data") or {}

                    if event_name == "on_tool_start" and run_name in _TOOL_NAMES:
                        yield {
                            "type": "tool_start",
                            "data": {
                                "tool": run_name,
                                "input": _truncate_value(data.get("input", {})),
                            },
                        }
                        continue

                    if event_name == "on_tool_end" and run_name in _TOOL_NAMES:
                        yield {
                            "type": "tool_end",
                            "data": {
                                "tool": run_name,
                                "output": _truncate_value(data.get("output", ""), limit=4000),
                            },
                        }
                        continue

                    if event_name == "on_chat_model_stream":
                        chunk = data.get("chunk")
                        content = getattr(chunk, "content", None)
                        text = _extract_text(content)
                        if text:
                            yield {
                                "type": "token",
                                "data": {
                                    "text": text,
                                },
                            }

                    if event_name == "on_chain_error":
                        error = data.get("error")
                        raise RuntimeError(str(error))

            except Exception as exc:
                yield {
                    "type": "error",
                    "data": {
                        "message": str(exc),
                    },
                }
                return

            yield {
                "type": "done",
                "data": {
                    "thread_id": thread_id,
                },
            }
        finally:
            reset_thread_id(token)
