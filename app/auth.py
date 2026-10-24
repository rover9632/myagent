from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.user_store import User


def _unauthorized(detail: str = "Invalid or expired session token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an Authorization header, or None if malformed."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def require_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Validate `Authorization: Bearer <session token>` against app.state.user_store.

    Return value is canonical for endpoints; the store lives on app.state so
    tests can swap in a fake (or use app.dependency_overrides[require_user]).
    """
    store = request.app.state.user_store
    token = _bearer_token(authorization)
    if token is None:
        raise _unauthorized()
    user = await store.user_for_token(token)
    if user is None:
        raise _unauthorized()
    return user
