"""Engine/sessionmaker factories for the ORM data layer (users/sessions/...).

Deliberately NOT module-level globals: building the engine at import time would
open connection pools whenever anything imports this module (tests included).
The lifespan in app/main.py calls build_engine()/build_sessionmaker() once and
disposes the engine on shutdown. The psycopg AsyncConnectionPool in main.py
stays alive in parallel -- AsyncPostgresSaver requires it; UserStore does not.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def get_url() -> str:
    """PG_URI is a plain libpq URI (see README); rewrite it to the psycopg3
    SQLAlchemy dialect (psycopg[binary] is already a runtime dependency)."""
    uri = get_settings().pg_uri
    if uri.startswith("postgresql://"):
        uri = uri.replace("postgresql://", "postgresql+psycopg://", 1)
    return uri


def build_engine(**kwargs) -> AsyncEngine:
    """Async engine over psycopg3. Extra kwargs override the defaults."""
    defaults: dict = {
        "echo": False,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    }
    defaults.update(kwargs)
    return create_async_engine(get_url(), **defaults)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
