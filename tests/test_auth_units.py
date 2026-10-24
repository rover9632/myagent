import hashlib

import pytest
from pydantic import ValidationError

from app.auth import _bearer_token
from app.schemas import LoginRequest, RegisterRequest
from app.user_store import (
    MAX_PASSWORD_BYTES,
    USERNAME_RE,
    PasswordTooLong,
    hash_password,
    token_hash,
    verify_password,
)

FAST_ROUNDS = 4  # keep bcrypt cheap in tests


@pytest.mark.parametrize(
    "username",
    ["abc", "a-b_C9", "0123456789", "a" * 32, "Alice"],
)
def test_username_regex_accepts_valid(username: str) -> None:
    assert USERNAME_RE.match(username)


@pytest.mark.parametrize(
    "username",
    [
        "ab",  # too short
        "a" * 33,  # too long
        "has space",
        "用户",
        "a.b",
        "alice:bob",  # ':' must stay out — checkpoint keys use it as separator
        "",
        "tab\tname",
    ],
)
def test_username_regex_rejects_invalid(username: str) -> None:
    assert not USERNAME_RE.match(username)


def test_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("correct horse battery", rounds=FAST_ROUNDS)
    assert hashed != "correct horse battery"
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong password", hashed)


def test_hash_rejects_over_72_bytes() -> None:
    with pytest.raises(PasswordTooLong):
        hash_password("a" * (MAX_PASSWORD_BYTES + 1), rounds=FAST_ROUNDS)


def test_verify_returns_false_for_over_72_bytes() -> None:
    hashed = hash_password("reference-pw", rounds=FAST_ROUNDS)
    # bcrypt 5 raises ValueError on long inputs; verify must swallow it as a
    # plain auth failure so login can never 500.
    assert not verify_password("a" * (MAX_PASSWORD_BYTES + 1), hashed)


def test_verify_returns_false_for_corrupt_hash() -> None:
    assert not verify_password("whatever", "not-a-bcrypt-hash")
    assert not verify_password("whatever", "")


def test_hash_uses_72_byte_boundary() -> None:
    pw = "a" * MAX_PASSWORD_BYTES
    hashed = hash_password(pw, rounds=FAST_ROUNDS)
    assert verify_password(pw, hashed)


def test_token_hash_is_stable_sha256_hex() -> None:
    token = "s3cret-token-value"
    h = token_hash(token)
    assert h == hashlib.sha256(token.encode()).hexdigest()
    assert len(h) == 64
    assert h == token_hash(token)
    assert h != token_hash(token + "x")


VALID_PASSWORD = "abcdefgh"  # 8 chars, 8 bytes — minimum accepted


@pytest.mark.parametrize("username", ["abc", "a-b_C9", "0123456789", "a" * 32])
def test_register_request_accepts_valid_username(username: str) -> None:
    assert RegisterRequest(username=username, password=VALID_PASSWORD).username == username


@pytest.mark.parametrize(
    "username",
    ["ab", "a" * 33, "has space", "用户", "a.b", "alice:bob", ""],
)
def test_register_request_rejects_invalid_username(username: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, password=VALID_PASSWORD)


def test_register_request_password_char_bounds() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username="abc", password="a" * 7)  # below min_length
    with pytest.raises(ValidationError):
        RegisterRequest(username="abc", password="a" * 73)  # above max_length
    assert RegisterRequest(username="abc", password="a" * 72).password == "a" * 72


def test_register_request_rejects_over_72_byte_password() -> None:
    cjk = "密" * 25  # 25 chars (within max_length) but 75 UTF-8 bytes
    assert len(cjk) == 25
    assert len(cjk.encode("utf-8")) == 75
    with pytest.raises(ValidationError):
        RegisterRequest(username="abc", password=cjk)


def test_login_request_is_lenient() -> None:
    # Long passwords must reach authenticate() so login answers 401, not 422.
    req = LoginRequest(username="abc", password="x" * 200)
    assert req.password == "x" * 200
    with pytest.raises(ValidationError):
        LoginRequest(username="abc", password="x" * 201)
    with pytest.raises(ValidationError):
        LoginRequest(username="", password="x")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer x", "x"),
        ("bearer  x ", "x"),
        ("token x", None),
        (None, None),
        ("Bearer ", None),
        ("Bearer", None),
        ("", None),
    ],
)
def test_bearer_token_parsing(header: str | None, expected: str | None) -> None:
    assert _bearer_token(header) == expected
