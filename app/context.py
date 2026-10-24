from contextvars import ContextVar

_current_thread_id: ContextVar[str | None] = ContextVar(
    "current_thread_id",
    default=None,
)


def set_thread_id(thread_id: str):
    return _current_thread_id.set(thread_id)


def reset_thread_id(token) -> None:
    _current_thread_id.reset(token)


def get_thread_id() -> str:
    thread_id = _current_thread_id.get()
    if not thread_id:
        raise RuntimeError("No agent thread_id is bound to the current tool execution context")
    return thread_id


_current_username: ContextVar[str | None] = ContextVar(
    "current_username",
    default=None,
)


def set_username(username: str):
    return _current_username.set(username)


def reset_username(token) -> None:
    _current_username.reset(token)


def get_username() -> str:
    username = _current_username.get()
    if not username:
        raise RuntimeError("No agent username is bound to the current tool execution context")
    return username
