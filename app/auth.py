from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status


async def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Enforce `Authorization: Bearer <token>` when a token is configured.

    The expected token is read from `app.state.api_token` at request time so
    it stays testable and hot-reloadable. An empty token disables auth, which
    the startup code warns about loudly - never silently.
    """
    expected = getattr(request.app.state, "api_token", "")
    if not expected:
        return

    scheme, _, provided = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(provided.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
