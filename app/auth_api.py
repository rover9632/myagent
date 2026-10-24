from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.auth import _bearer_token, require_user
from app.schemas import AuthResponse, LoginRequest, MeResponse, RegisterRequest
from app.user_store import DuplicateUsername, User

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, body: RegisterRequest) -> AuthResponse:
    """Create a user and auto-login: the 201 body already carries a session token."""
    store = request.app.state.user_store
    try:
        user = await store.create_user(body.username, body.password)
    except DuplicateUsername:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already exists",
        ) from None
    token, expires = await store.create_session(user.id)
    return AuthResponse(token=token, username=user.username, expires_at=expires)


@router.post("/login", response_model=AuthResponse)
async def login(request: Request, body: LoginRequest) -> AuthResponse:
    """Verify credentials and issue a FRESH token on every login (no fixation)."""
    store = request.app.state.user_store
    user = await store.authenticate(body.username, body.password)
    if user is None:
        # Identical detail for unknown user / wrong password (anti-enumeration);
        # UserStore.authenticate burns a dummy bcrypt check to equalize timing.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires = await store.create_session(user.id)
    return AuthResponse(token=token, username=user.username, expires_at=expires)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(
    request: Request,
    _user: Annotated[User, Depends(require_user)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Server-side revoke of the presented session token."""
    token = _bearer_token(authorization)
    if token is not None:  # require_user already proved it valid
        await request.app.state.user_store.revoke_token(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[User, Depends(require_user)]) -> MeResponse:
    return MeResponse(username=user.username)
