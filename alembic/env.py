"""Alembic environment: users/sessions schema only.

The checkpoint* tables belong to AsyncPostgresSaver.setup() (its own
checkpoint_migrations ledger); the include_object filter below is the load-
bearing guard that keeps autogenerate from ever proposing DROP TABLE for them.

Never import app.main here -- app.config + app.db_schema have no side effects
beyond reading .env, but app.main would wire the whole lifespan. Migrations
therefore must run from the repo root (same CWD convention as uvicorn).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db_schema import metadata as target_metadata

config = context.config


def _include_object(name, type_, reflected, compare_to) -> bool:
    """Only tables declared in our metadata participate in autogenerate."""
    if type_ == "table":
        return name in target_metadata.tables
    return True


def _url() -> str:
    """PG_URI is a plain libpq URI (see README); migrations use the psycopg3
    sync dialect (psycopg[binary] is already a runtime dependency)."""
    uri = get_settings().pg_uri
    if uri.startswith("postgresql://"):
        uri = uri.replace("postgresql://", "postgresql+psycopg://", 1)
    return uri


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_object=_include_object,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
