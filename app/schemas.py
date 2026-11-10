from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.user_store import normalize_phone

# Same grammar as app.user_store.USERNAME_RE — keep the two in sync.
USERNAME_PATTERN = r"^[a-zA-Z][a-zA-Z0-9_-]{3,31}$"


def _blank_to_none(v: object) -> object:
    # "optional" means an untouched HTML field ("") is absent, not invalid.
    # Applied in mode="before": "" would fail EmailStr core validation before
    # any mode="after" hook could see it. Shared by Register/MePatch.
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v


def _lowercase_email(v: str | None) -> str | None:
    # Case-insensitive uniqueness is enforced write-side: all rows are stored
    # lowercase, so uq_users_email collapses Bob@X / bob@x.
    return v.lower() if v is not None else None


def _normalize_phone_value(v: str | None) -> str | None:
    # E.164 with mainland China (+86) as the default region; ValueError → 422.
    return normalize_phone(v) if v is not None else None


def _reject_bcrypt_oversize(value: str, label: str) -> str:
    # max_length counts chars; bcrypt silently truncates (bcrypt 5 raises) past
    # 72 UTF-8 bytes — reject at the API edge instead. Chars ≠ bytes for CJK.
    if len(value.encode("utf-8")) > 72:
        raise ValueError(f"{label} must not exceed 72 bytes")
    return value


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
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=72)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("email", "phone", mode="before")
    @classmethod
    def _blank_optional_to_none(cls, v: object) -> object:
        return _blank_to_none(v)

    @field_validator("email", mode="after")
    @classmethod
    def _lowercase_email(cls, v: str | None) -> str | None:
        return _lowercase_email(v)

    @field_validator("phone", mode="after")
    @classmethod
    def _normalize_phone(cls, v: str | None) -> str | None:
        return _normalize_phone_value(v)

    @model_validator(mode="after")
    def _password_within_bcrypt_limit(self) -> Self:
        _reject_bcrypt_oversize(self.password, "password")
        return self


class LoginRequest(BaseModel):
    # Lenient caps: login input is only compared, never stored. Over-72-byte
    # passwords simply fail authentication (401), never a validation error.
    # account may be a username, email, or phone; classification/normalization
    # happens in UserStore.classify_account — never here, so a malformed
    # phone/email can only 401, never 422.
    account: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    token: str
    username: str
    expires_at: datetime


class MeResponse(BaseModel):
    username: str


class MePatchRequest(BaseModel):
    """PATCH /v1/me: only keys the client actually sent are applied.

    The endpoint uses ``model_dump(exclude_unset=True)`` — absent means
    untouched, explicit null/"" means clear (for the nullable ones). Length
    ceilings mirror the DB columns so oversized strings 422 here instead of
    500 at the DB. The web UI PATCHes one field at a time; update_me's
    change-detection additionally makes a same-value resubmit safe for
    *_verified_at.
    """

    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    display_name: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=2048)
    bio: str | None = Field(default=None, max_length=5000)
    # NOT NULL columns: clearing is a 422, never a silent default. The ""
    # default exists only to make the field optional; exclude_unset never
    # emits it, so it is unobservable downstream.
    locale: str = Field(default="", min_length=1, max_length=20)
    timezone: str = Field(default="", min_length=1, max_length=64)

    @field_validator("email", "phone", "display_name", "avatar_url", "bio", mode="before")
    @classmethod
    def _blank_optional_to_none(cls, v: object) -> object:
        return _blank_to_none(v)

    @field_validator("email", mode="after")
    @classmethod
    def _lowercase_email(cls, v: str | None) -> str | None:
        return _lowercase_email(v)

    @field_validator("phone", mode="after")
    @classmethod
    def _normalize_phone(cls, v: str | None) -> str | None:
        return _normalize_phone_value(v)


class ChangePasswordRequest(BaseModel):
    # current_password is lenient like LoginRequest: it is only ever compared,
    # so over-long/garbage input fails verification (403), never a 422.
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=72)

    @model_validator(mode="after")
    def _new_password_within_bcrypt_limit(self) -> Self:
        _reject_bcrypt_oversize(self.new_password, "new_password")
        return self


class MeProfileResponse(BaseModel):
    """Flat mirror of app.user_store.MeData (never carries password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str | None
    phone: str | None
    status: str
    email_verified_at: datetime | None
    phone_verified_at: datetime | None
    last_login_at: datetime | None
    last_login_ip: str | None
    created_at: datetime
    display_name: str | None
    avatar_url: str | None
    bio: str | None
    locale: str
    timezone: str
