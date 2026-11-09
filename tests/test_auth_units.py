import hashlib

import pytest
from pydantic import ValidationError

from app.auth import _bearer_token
from app.schemas import LoginRequest, RegisterRequest
from app.user_store import (
    MAX_PASSWORD_BYTES,
    USERNAME_RE,
    PasswordTooLong,
    classify_account,
    hash_password,
    normalize_phone,
    token_hash,
    verify_password,
)

FAST_ROUNDS = 4  # keep bcrypt cheap in tests

VALID_USERNAME = "abcd"  # 4 chars, letter start — smallest accepted


@pytest.mark.parametrize(
    "username",
    ["abcd", "a-b_C9", "a" * 32, "Alice", "bob_1"],
)
def test_username_regex_accepts_valid(username: str) -> None:
    assert USERNAME_RE.match(username)


@pytest.mark.parametrize(
    "username",
    [
        "abc",  # too short (min is now 4)
        "ab",  # too short
        "1abcd",  # must start with a letter
        "0123456789",  # digit start
        "-abc",  # punctuation start
        "_abc",  # punctuation start
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


@pytest.mark.parametrize("username", ["abcd", "a-b_C9", "a" * 32])
def test_register_request_accepts_valid_username(username: str) -> None:
    assert RegisterRequest(username=username, password=VALID_PASSWORD).username == username


@pytest.mark.parametrize(
    "username",
    ["abc", "1abcd", "ab", "a" * 33, "has space", "用户", "a.b", "alice:bob", ""],
)
def test_register_request_rejects_invalid_username(username: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, password=VALID_PASSWORD)


def test_register_request_password_char_bounds() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username=VALID_USERNAME, password="a" * 7)  # below min_length
    with pytest.raises(ValidationError):
        RegisterRequest(username=VALID_USERNAME, password="a" * 73)  # above max_length
    assert RegisterRequest(username=VALID_USERNAME, password="a" * 72).password == "a" * 72


def test_register_request_rejects_over_72_byte_password() -> None:
    cjk = "密" * 25  # 25 chars (within max_length) but 75 UTF-8 bytes
    assert len(cjk) == 25
    assert len(cjk.encode("utf-8")) == 75
    with pytest.raises(ValidationError):
        RegisterRequest(username=VALID_USERNAME, password=cjk)


def test_register_email_normalized_and_optional() -> None:
    req = RegisterRequest(username=VALID_USERNAME, password=VALID_PASSWORD, email="Bob@Example.com")
    assert req.email == "bob@example.com"  # case-insensitive uniqueness is write-side
    blank = RegisterRequest(username=VALID_USERNAME, password=VALID_PASSWORD, email="   ")
    assert blank.email is None
    absent = RegisterRequest(username=VALID_USERNAME, password=VALID_PASSWORD)
    assert absent.email is None
    with pytest.raises(ValidationError):
        RegisterRequest(username=VALID_USERNAME, password=VALID_PASSWORD, email="not-an-email")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("13800138000", "+8613800138000"),  # bare CN mobile defaults to +86
        ("138 0013 8000", "+8613800138000"),
        ("+86 138-0013-8000", "+8613800138000"),
        ("008613800138000", "+8613800138000"),  # 00 international prefix
        ("+1 650 555 0123", "+16505550123"),  # explicit country code kept
    ],
)
def test_register_phone_normalized_to_e164(raw: str, expected: str) -> None:
    req = RegisterRequest(username=VALID_USERNAME, password=VALID_PASSWORD, phone=raw)
    assert req.phone == expected


@pytest.mark.parametrize("raw", ["123", "abc", "+0", "138001380001234567"])
def test_register_rejects_invalid_phone(raw: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username=VALID_USERNAME, password=VALID_PASSWORD, phone=raw)


def test_register_phone_blank_is_absent() -> None:
    req = RegisterRequest(username=VALID_USERNAME, password=VALID_PASSWORD, phone="  ")
    assert req.phone is None


def test_normalize_phone_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="not a valid number"):
        normalize_phone("hello")


@pytest.mark.parametrize(
    ("account", "expected"),
    [
        ("alice", ("alice", None, None)),
        ("BOB@X.com", ("BOB@X.com", "bob@x.com", None)),
        ("138 0013 8000", ("138 0013 8000", None, "+8613800138000")),
        ("+8613800138000", ("+8613800138000", None, "+8613800138000")),
        # malformed phones never raise — they degrade to a username lookup
        ("+0123bogus", ("+0123bogus", None, None)),
        ("0123", ("0123", None, None)),
    ],
)
def test_classify_account(account: str, expected: tuple) -> None:
    assert classify_account(account) == expected


def test_login_request_is_lenient() -> None:
    # Long passwords must reach authenticate() so login answers 401, not 422.
    req = LoginRequest(account=VALID_USERNAME, password="x" * 200)
    assert req.password == "x" * 200
    with pytest.raises(ValidationError):
        LoginRequest(account=VALID_USERNAME, password="x" * 201)
    with pytest.raises(ValidationError):
        LoginRequest(account="", password="x")
    # account absorbs any identifier form without schema-level validation
    req2 = LoginRequest(account="someone@example.com", password="x")
    assert req2.account == "someone@example.com"
    with pytest.raises(ValidationError):
        LoginRequest(account="a" * 321, password="x")  # above the 320 cap


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
