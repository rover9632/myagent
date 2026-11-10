from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
import phonenumbers
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.dbmodels.session import Session as SessionORM
from app.dbmodels.user import User as UserORM
from app.dbmodels.user_profile import UserProfile

# Same grammar as app.schemas.USERNAME_PATTERN — keep the two in sync.
USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{3,31}$")
MAX_PASSWORD_BYTES = 72
BCRYPT_ROUNDS = 12
DEFAULT_PHONE_REGION = "CN"


class DuplicateUsername(Exception):
    pass


class DuplicateEmail(Exception):
    pass


class DuplicatePhone(Exception):
    pass


class PasswordTooLong(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    username: str


@dataclass(frozen=True, slots=True)
class MeData:
    """Everything the profile center shows — never carries password_hash/deleted_at.

    ``user_profiles`` rows are lazily created on first PATCH (nothing creates them
    at register), so when the row is absent ``get_me`` synthesizes the same column
    defaults the ORM declares (zh-CN / Asia/Shanghai).
    """

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


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ip_str(value: object) -> str | None:
    """Normalize an INET-column read value to str|None (MeData's contract).

    psycopg returns ``ipaddress.IPv4Address/IPv6Address`` objects for INET
    columns — and a stored IPv4 often comes back in ``::ffff:``-mapped IPv6
    form — while the response model expects a plain string. Normalizing at the
    read edge keeps the dataclass honest instead of exploding in FastAPI
    serialization (500).
    """
    return None if value is None else str(value)


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


def normalize_phone(raw: str) -> str:
    """Return the E.164 form or raise ValueError. Bare/national numbers default
    to mainland China (+86); international numbers need an explicit +country."""
    try:
        parsed = phonenumbers.parse(raw.strip(), DEFAULT_PHONE_REGION)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("phone is not a valid number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("phone is not a valid number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def classify_account(account: str) -> tuple[str, str | None, str | None]:
    """Split a login account string into (username_candidate, email, e164_phone).

    Detection: '@' wins as email; a '+'-prefixed or digit-only/separator string
    is attempted as a phone. Never raises — a malformed phone just falls back to
    the username branch (login failures are 401, never 422/500). Shared by the
    real store and tests/conftest FakeUserStore.
    """
    acct = account.strip()
    if "@" in acct:
        return acct, acct.lower(), None
    compact = re.sub(r"[()\-. ]", "", acct)
    if compact.startswith("+") or compact.isdigit():
        try:
            return acct, None, normalize_phone(compact)
        except ValueError:
            pass
    return acct, None, None


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
    the functional unique index on ``lower(users.username)``. Email/phone are
    optional registrations; emails are stored lowercase (uniqueness collapses
    write-side) and phones canonicalized to E.164, and ``authenticate`` accepts
    any of the three identifier forms via :func:`classify_account`.
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

    async def create_user(
        self,
        username: str,
        password: str,
        *,
        email: str | None = None,
        phone: str | None = None,
    ) -> User:
        # Friendly-error pre-check; the unique constraints below remain the
        # authoritative race backstop.
        conds = [func.lower(UserORM.username) == func.lower(username)]
        if email is not None:
            conds.append(UserORM.email == email)
        if phone is not None:
            conds.append(UserORM.phone == phone)
        async with self.sessionmaker() as session:
            stmt = select(UserORM.username, UserORM.email, UserORM.phone).where(or_(*conds))
            existing = (await session.execute(stmt)).first()
        if existing is not None:
            # Priority mirrors the login tie-break: username > email > phone.
            if existing.username is not None and existing.username.lower() == username.lower():
                raise DuplicateUsername(username)
            if email is not None and existing.email == email:
                raise DuplicateEmail(username)
            if phone is not None and existing.phone == phone:
                raise DuplicatePhone(username)
        hashed = await asyncio.to_thread(hash_password, password, rounds=self.bcrypt_rounds)
        user = UserORM(username=username, password_hash=hashed, email=email, phone=phone)
        try:
            async with self.sessionmaker() as session, session.begin():
                session.add(user)
                await session.flush()  # populates user.id (python-side uuid4 default)
        except IntegrityError as exc:
            constraint = getattr(exc.orig, "constraint_name", None) or ""
            if constraint == "uq_users_email":
                raise DuplicateEmail(username) from exc
            if constraint == "uq_users_phone":
                raise DuplicatePhone(username) from exc
            # uq_users_username, the functional lower(username) unique index,
            # or an unknown constraint: only username is always non-NULL.
            raise DuplicateUsername(username) from exc
        return User(id=user.id, username=user.username)

    async def authenticate(self, account: str, password: str) -> User | None:
        username_part, email_part, phone_part = classify_account(account)
        username_cond = func.lower(UserORM.username) == func.lower(username_part)
        conds = [username_cond]
        if email_part is not None:
            conds.append(UserORM.email == email_part)  # stored lowercase at write time
        if phone_part is not None:
            conds.append(UserORM.phone == phone_part)  # canonical E.164
        # Deterministic tie-break when one string matches two identities
        # (e.g. a legacy digit username that is also someone's phone): username wins.
        stmt = (
            select(UserORM.id, UserORM.username, UserORM.password_hash)
            .where(or_(*conds))
            .order_by(case((username_cond, 0), else_=1), UserORM.id)
            .limit(1)
        )
        async with self.sessionmaker() as session:
            row = (await session.execute(stmt)).first()
        if row is None or row.password_hash is None:
            await self._burn_time(password)  # reduce user-enumeration timing signal
            return None
        ok = await asyncio.to_thread(verify_password, password, row.password_hash)
        return User(id=row.id, username=row.username) if ok else None

    async def touch_login(self, user_id: UUID, ip: str | None) -> None:
        """Record a successful login (timestamp + client IP) on the user row.

        ``ip`` must already be validated/normalized by the caller — the INET
        column rejects garbage and a failed write must never mask a good login,
        so auth_api only ever passes None or a parseable address.
        """
        stmt = (
            update(UserORM)
            .where(UserORM.id == user_id)
            .values(last_login_at=func.now(), last_login_ip=ip)
        )
        async with self.sessionmaker() as session, session.begin():
            await session.execute(stmt)

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

    async def revoke_other_sessions(self, user_id: UUID, keep_token: str | None) -> int:
        """Drop every session of the user except ``keep_token`` (the acting one).

        Called after a successful password change so other devices get logged
        out while the current tab survives. Returns the number of rows deleted.
        """
        stmt = delete(SessionORM).where(SessionORM.user_id == user_id)
        if keep_token:
            stmt = stmt.where(SessionORM.token_hash != token_hash(keep_token))
        async with self.sessionmaker() as session, session.begin():
            result = await session.execute(stmt)
        return result.rowcount or 0

    async def get_me(self, user_id: UUID) -> MeData | None:
        """Read the profile-center view: users row + user_profiles row (or defaults).

        Two plain reads, no write — a missing profile row is synthesized with the
        ORM's column defaults. None when the users row vanished under a live token.
        """
        stmt = select(
            UserORM.id,
            UserORM.username,
            UserORM.email,
            UserORM.phone,
            UserORM.status,
            UserORM.email_verified_at,
            UserORM.phone_verified_at,
            UserORM.last_login_at,
            UserORM.last_login_ip,
            UserORM.created_at,
        ).where(UserORM.id == user_id)
        prof_stmt = select(
            UserProfile.display_name,
            UserProfile.avatar_url,
            UserProfile.bio,
            UserProfile.locale,
            UserProfile.timezone,
        ).where(UserProfile.user_id == user_id)
        async with self.sessionmaker() as session:
            row = (await session.execute(stmt)).first()
            if row is None:
                return None
            prof = (await session.execute(prof_stmt)).first()
        return MeData(
            id=row.id,
            username=row.username,
            email=row.email,
            phone=row.phone,
            status=row.status,
            email_verified_at=row.email_verified_at,
            phone_verified_at=row.phone_verified_at,
            last_login_at=row.last_login_at,
            last_login_ip=ip_str(row.last_login_ip),
            created_at=row.created_at,
            display_name=prof.display_name if prof else None,
            avatar_url=prof.avatar_url if prof else None,
            bio=prof.bio if prof else None,
            locale=prof.locale if prof else "zh-CN",
            timezone=prof.timezone if prof else "Asia/Shanghai",
        )

    async def update_me(self, user_id: UUID, changes: Mapping[str, Any]) -> None:
        """Apply a PATCH /v1/me in ONE transaction (contact half + profile half).

        ``changes`` is ``model_dump(exclude_unset=True)``: key present == the
        client intends to write it (None/"" already normalized to None by the
        schema = clear), key absent == leave untouched. An empty mapping is a
        complete no-op — it must not create a profile row or bump updated_at.

        ``*_verified_at`` resets only when the canonical value actually
        differs, so a same-value resubmit (the web UI now PATCHes one field
        at a time, but this stays true for any client) never wipes the 已验证
        badge.
        Values arrive pre-normalized (lowercase email, E.164 phone) from the
        schema, so plain ``!=`` comparison is already canonical-aware.
        """
        if not changes:
            return
        profile_keys = ("display_name", "avatar_url", "bio", "locale", "timezone")
        profile_changes = {k: changes[k] for k in profile_keys if k in changes}
        try:
            async with self.sessionmaker() as session, session.begin():
                row = (
                    await session.execute(
                        select(
                            UserORM.email,
                            UserORM.phone,
                            UserORM.email_verified_at,
                            UserORM.phone_verified_at,
                        ).where(UserORM.id == user_id)
                    )
                ).first()
                if row is None:
                    return  # user vanished; the endpoint's re-read surfaces the 404
                values: dict[str, Any] = {}
                if "email" in changes and changes["email"] != row.email:
                    values["email"] = changes["email"]
                    values["email_verified_at"] = None
                if "phone" in changes and changes["phone"] != row.phone:
                    values["phone"] = changes["phone"]
                    values["phone_verified_at"] = None
                for field, exc_cls in (("email", DuplicateEmail), ("phone", DuplicatePhone)):
                    if field not in values or values[field] is None:
                        continue
                    # Friendly pre-check excluding own row (re-submitting one's own
                    # email is a no-op above, but a case/E.164 rewrite could land
                    # here); the unique constraints stay the race backstop below.
                    clash = (
                        await session.execute(
                            select(UserORM.id).where(
                                getattr(UserORM, field) == values[field], UserORM.id != user_id
                            )
                        )
                    ).first()
                    if clash is not None:
                        raise exc_cls(str(user_id))
                if values:
                    await session.execute(
                        update(UserORM).where(UserORM.id == user_id).values(**values)
                    )
                if profile_changes:
                    prow = (
                        await session.execute(
                            select(UserProfile.user_id).where(UserProfile.user_id == user_id)
                        )
                    ).first()
                    if prow is not None:
                        await session.execute(
                            update(UserProfile)
                            .where(UserProfile.user_id == user_id)
                            .values(**profile_changes)
                        )
                    else:
                        # ORM insert so the Python-side defaults fire — attributes
                        # is NOT NULL with no server default, locale/timezone too.
                        session.add(UserProfile(user_id=user_id, **profile_changes))
        except IntegrityError as exc:
            constraint = getattr(exc.orig, "constraint_name", None) or ""
            if constraint == "uq_users_email":
                raise DuplicateEmail(str(user_id)) from exc
            if constraint == "uq_users_phone":
                raise DuplicatePhone(str(user_id)) from exc
            raise

    async def change_password(
        self, user_id: UUID, current_password: str, new_password: str
    ) -> bool:
        """Verify the current password and re-hash the new one; False == rejected.

        Mirrors ``authenticate``'s failure posture: a NULL hash (legacy row with
        no password) burns dummy-checkpw time and fails like any wrong password,
        and an over-72-byte ``current_password`` degrades to False inside
        ``verify_password`` — never a 500. The caller must pre-reject an
        over-long ``new_password`` at the schema edge (bcrypt 5 raises).
        """
        async with self.sessionmaker() as session:
            row = (
                await session.execute(select(UserORM.password_hash).where(UserORM.id == user_id))
            ).first()
        if row is None:
            return False
        if row.password_hash is None:
            await self._burn_time(current_password)
            return False
        ok = await asyncio.to_thread(verify_password, current_password, row.password_hash)
        if not ok:
            return False
        hashed = await asyncio.to_thread(hash_password, new_password, rounds=self.bcrypt_rounds)
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                update(UserORM).where(UserORM.id == user_id).values(password_hash=hashed)
            )
        return True

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
