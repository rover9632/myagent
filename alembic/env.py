"""Alembic environment: app-owned tables, sourced from the ORM models.

The single source of truth is `app.db.base.Base.metadata`, populated by
importing `app.dbmodels` (each module registers its table on Base). Edit a
model, then `alembic revision --autogenerate` -- there is no hand-maintained
Core metadata anymore (the old app/db_schema.py is retired).

The checkpoint* tables belong to AsyncPostgresSaver.setup() (its own
checkpoint_migrations ledger); the include_object filter below is the load-
bearing guard that keeps autogenerate from ever proposing DROP TABLE for them.

Never import app.main here -- importing the engine in app.db.session would
build a live connection pool at migration time, and app.main would wire the
whole lifespan. Migrations therefore must run from the repo root (same CWD
convention as uvicorn) so .env is picked up by app.config.
"""

from __future__ import annotations

import app.dbmodels  # noqa: F401  (registers every model on Base.metadata)
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata


def _include_object(object, name, type_, reflected, compare_to) -> bool:
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
