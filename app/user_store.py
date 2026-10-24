from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
from psycopg.errors import UniqueViolation

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
MAX_PASSWORD_BYTES = 72
BCRYPT_ROUNDS = 12


class DuplicateUsername(Exception):
    pass


class PasswordTooLong(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str


# Executed one-by-one (never as a multi-statement string). Idempotent — safe on
# every startup. No alembic (MVP).
DDL_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS users (
           id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
           username      TEXT NOT NULL,
           password_hash TEXT NOT NULL,
           created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS users_username_uidx ON users (username)",
    # Case-insensitive uniqueness without the citext extension (anti-impersonation).
    "CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_uidx ON users (lower(username))",
    """CREATE TABLE IF NOT EXISTS sessions (
           token_hash TEXT PRIMARY KEY,
           user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           expires_at TIMESTAMPTZ NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    "CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at)",
)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, *, rounds: int = BCRYPT_ROUNDS) -> str:
    pw = password.encode()
    if len(pw) > MAX_PASSWORD_BYTES:
        raise PasswordTooLong("password must not exceed 72 bytes")
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    pw = password.encode()
    if len(pw) > MAX_PASSWORD_BYTES:
        return False  # bcrypt 5 would raise; long login input is just a failed login
    try:
        return bcrypt.checkpw(pw, password_hash.encode())
    except ValueError:
        return False  # corrupt stored hash -> treat as auth failure, never 500


class UserStore:
    """Thin data-access layer over the shared psycopg AsyncConnectionPool.

    The pool is configured with autocommit=True + dict_row, so every execute
    stands alone and rows come back as dicts. These methods are the contract
    FakeUserStore mirrors in tests.
    """

    def __init__(
        self,
        pool,
        *,
        session_ttl_days: int = 30,
        bcrypt_rounds: int = BCRYPT_ROUNDS,
    ) -> None:
        self.pool = pool
        self.session_ttl_days = session_ttl_days
        self.bcrypt_rounds = bcrypt_rounds
        self._last_purge = 0.0
        self._dummy_hash: str | None = None

    async def bootstrap(self) -> None:
        async with self.pool.connection() as conn, conn.cursor() as cur:
            for stmt in DDL_STATEMENTS:
                await cur.execute(stmt)

    async def create_user(self, username: str, password: str) -> User:
        hashed = await asyncio.to_thread(hash_password, password, rounds=self.bcrypt_rounds)
        try:
            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
                    (username, hashed),
                )
                row = await cur.fetchone()
        except UniqueViolation as exc:
            raise DuplicateUsername(username) from exc
        return User(id=row["id"], username=username)

    async def authenticate(self, username: str, password: str) -> User | None:
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT id, username, password_hash FROM users "
                "WHERE lower(username) = lower(%s)",
                (username,),
            )
            row = await cur.fetchone()
        if row is None:
            await self._burn_time(password)  # reduce user-enumeration timing signal
            return None
        ok = await asyncio.to_thread(verify_password, password, row["password_hash"])
        return User(id=row["id"], username=row["username"]) if ok else None

    async def create_session(self, user_id: int) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)  # 256 bits of entropy, 43 chars
        expires = datetime.now(UTC) + timedelta(days=self.session_ttl_days)
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (token_hash(token), user_id, expires),
            )
        return token, expires

    async def user_for_token(self, token: str) -> User | None:
        await self._purge_expired_throttled()
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT u.id, u.username FROM sessions s "
                "JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = %s AND s.expires_at > now()",
                (token_hash(token),),
            )
            row = await cur.fetchone()
        return User(id=row["id"], username=row["username"]) if row else None

    async def revoke_token(self, token: str) -> None:
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(token),))

    async def _purge_expired_throttled(self, interval_seconds: float = 300.0) -> None:
        now = time.monotonic()
        if now - self._last_purge < interval_seconds:
            return
        self._last_purge = now
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM sessions WHERE expires_at <= now()")

    async def _burn_time(self, password: str) -> None:
        if self._dummy_hash is None:
            self._dummy_hash = await asyncio.to_thread(
                hash_password, "timing-equalizer", rounds=self.bcrypt_rounds
            )
        await asyncio.to_thread(verify_password, password, self._dummy_hash)
