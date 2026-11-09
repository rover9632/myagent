from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.auth import _bearer_token, require_user
from app.schemas import AuthResponse, LoginRequest, MeResponse, RegisterRequest
from app.user_store import DuplicateEmail, DuplicatePhone, DuplicateUsername, User

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """Best-effort client address for the last_login_ip audit column.

    Behind the Next proxy (web/) the socket peer is the proxy itself, so the
    forwarded chain is tried first — but every candidate is parsed through
    ipaddress: garbage XFF entries are skipped and a fully bogus header falls
    back to the socket peer, so the INET write can never be handed junk.
    """
    candidates: list[str] = []
    xff = request.headers.get("x-forwarded-for")
    if xff:
        candidates.extend(part.strip() for part in xff.split(","))
    if request.client and request.client.host:
        candidates.append(request.client.host)
    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, body: RegisterRequest) -> AuthResponse:
    """Create a user (optional email/phone) and auto-login.

    The 201 body already carries a session token.
    """
    store = request.app.state.user_store
    try:
        user = await store.create_user(
            body.username, body.password, email=body.email, phone=body.phone
        )
    except DuplicateUsername:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already exists",
        ) from None
    except DuplicateEmail:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already exists",
        ) from None
    except DuplicatePhone:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="phone already exists",
        ) from None
    token, expires = await store.create_session(user.id)
    return AuthResponse(token=token, username=user.username, expires_at=expires)


@router.post("/login", response_model=AuthResponse)
async def login(request: Request, body: LoginRequest) -> AuthResponse:
    """Verify credentials (username/email/phone in `account`).

    Issues a FRESH token on every login (no fixation).
    """
    store = request.app.state.user_store
    user = await store.authenticate(body.account, body.password)
    if user is None:
        # Identical detail for unknown user / wrong password (anti-enumeration);
        # UserStore.authenticate burns a dummy bcrypt check to equalize timing.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Audit trail BEFORE the token is issued: a failed touch must not leave a
    # live session with no recorded login.
    await store.touch_login(user.id, _client_ip(request))
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
