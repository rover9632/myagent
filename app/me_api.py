from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.auth import _bearer_token, require_user
from app.schemas import ChangePasswordRequest, MePatchRequest, MeProfileResponse
from app.user_store import DuplicateEmail, DuplicatePhone, MeData, User

# Full paths spelled per route (no prefix) to dodge the prefix+"/" trap.
router = APIRouter(tags=["me"])


async def _get_me_or_404(store, user_id) -> MeData:
    data = await store.get_me(user_id)
    if data is None:
        # Live token but gone user row (deleted between require_user and here).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user not found",
        ) from None
    return data


@router.get("/v1/me", response_model=MeProfileResponse)
async def get_me(
    request: Request,
    user: Annotated[User, Depends(require_user)],
) -> MeProfileResponse:
    """Account + profile view for the profile center (never password_hash)."""
    data = await _get_me_or_404(request.app.state.user_store, user.id)
    return MeProfileResponse.model_validate(data)


@router.patch("/v1/me", response_model=MeProfileResponse)
async def patch_me(
    request: Request,
    body: MePatchRequest,
    user: Annotated[User, Depends(require_user)],
) -> MeProfileResponse:
    """Atomically update contact fields and profile fields in one transaction.

    exclude_unset is the wire semantics: absent == untouched, ""/null == clear
    (nullable fields only). A 409 rolls the whole request back, so the client
    can re-submit after fixing the conflicting value.
    """
    store = request.app.state.user_store
    try:
        await store.update_me(user.id, body.model_dump(exclude_unset=True))
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
    data = await _get_me_or_404(store, user.id)
    return MeProfileResponse.model_validate(data)


@router.post("/v1/me/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: Annotated[User, Depends(require_user)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Re-verify the current password, re-hash, and log out other devices.

    403 (not 401!) for a wrong current password: 401 is reserved for a dead
    session token, which is what the web shell keys its auto-logout on. The
    presented token survives; every other session of the user is revoked.
    """
    store = request.app.state.user_store
    ok = await store.change_password(user.id, body.current_password, body.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="current password is incorrect",
        ) from None
    await store.revoke_other_sessions(user.id, _bearer_token(authorization))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
