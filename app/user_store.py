from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.dbmodels.session import Session as SessionORM
from app.dbmodels.user import User as UserORM

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
MAX_PASSWORD_BYTES = 72
BCRYPT_ROUNDS = 12


class DuplicateUsername(Exception):
    pass


class PasswordTooLong(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    username: str


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
    """Thin data-access layer over the SQLAlchemy ORM (app/dbmodels).

    Constructed with an async_sessionmaker built in the lifespan
    (app/db/session.py factories); every method is a standalone unit of work
    that commits exactly once. These methods are the contract FakeUserStore
    mirrors in tests. Schema creation is NOT this layer's job: the app tables
    are owned by Alembic (``alembic/versions/``, run ``uv run alembic upgrade
    head`` before booting after any schema change).

    Case-insensitive username handling (anti-impersonation) mirrors the old
    store: lookups use ``lower(username)`` and the DB enforces uniqueness via
    the functional unique index on ``lower(users.username)``.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        session_ttl_days: int = 30,
        bcrypt_rounds: int = BCRYPT_ROUNDS,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.session_ttl_days = session_ttl_days
        self.bcrypt_rounds = bcrypt_rounds
        self._last_purge = 0.0
        self._dummy_hash: str | None = None

    async def create_user(self, username: str, password: str) -> User:
        hashed = await asyncio.to_thread(hash_password, password, rounds=self.bcrypt_rounds)
        user = UserORM(username=username, password_hash=hashed)
        try:
            async with self.sessionmaker() as session, session.begin():
                session.add(user)
                await session.flush()  # populates user.id (python-side uuid4 default)
        except IntegrityError as exc:
            # uq_users_username or the functional lower(username) unique index.
            raise DuplicateUsername(username) from exc
        return User(id=user.id, username=user.username)

    async def authenticate(self, username: str, password: str) -> User | None:
        stmt = select(UserORM.id, UserORM.username, UserORM.password_hash).where(
            func.lower(UserORM.username) == func.lower(username)
        )
        async with self.sessionmaker() as session:
            row = (await session.execute(stmt)).first()
        if row is None or row.password_hash is None:
            await self._burn_time(password)  # reduce user-enumeration timing signal
            return None
        ok = await asyncio.to_thread(verify_password, password, row.password_hash)
        return User(id=row.id, username=row.username) if ok else None

    async def create_session(self, user_id: UUID) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)  # 256 bits of entropy, 43 chars
        expires = datetime.now(UTC) + timedelta(days=self.session_ttl_days)
        async with self.sessionmaker() as session, session.begin():
            session.add(
                SessionORM(token_hash=token_hash(token), user_id=user_id, expires_at=expires)
            )
        return token, expires

    async def user_for_token(self, token: str) -> User | None:
        await self._purge_expired_throttled()
        stmt = (
            select(UserORM.id, UserORM.username)
            .join(SessionORM, SessionORM.user_id == UserORM.id)
            .where(SessionORM.token_hash == token_hash(token), SessionORM.expires_at > func.now())
        )
        async with self.sessionmaker() as session:
            row = (await session.execute(stmt)).first()
        return User(id=row.id, username=row.username) if row else None

    async def revoke_token(self, token: str) -> None:
        stmt = delete(SessionORM).where(SessionORM.token_hash == token_hash(token))
        async with self.sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def _purge_expired_throttled(self, interval_seconds: float = 300.0) -> None:
        now = time.monotonic()
        if now - self._last_purge < interval_seconds:
            return
        self._last_purge = now
        stmt = delete(SessionORM).where(SessionORM.expires_at <= func.now())
        async with self.sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def _burn_time(self, password: str) -> None:
        if self._dummy_hash is None:
            self._dummy_hash = await asyncio.to_thread(
                hash_password, "timing-equalizer", rounds=self.bcrypt_rounds
            )
        await asyncio.to_thread(verify_password, password, self._dummy_hash)
