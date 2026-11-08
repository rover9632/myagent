"""Pin app/dbmodels metadata (Base.metadata) -- the Alembic baseline's source of truth.

Pure in-memory compilation (postgresql dialect) -- no PostgreSQL needed. These
assertions keep `alembic revision --autogenerate` from silently diverging from
the schema the ORM models promise.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

import app.dbmodels  # noqa: F401  (registers every model on Base.metadata)
from app.db.base import Base

APP_TABLES = {
    "users",
    "sessions",
    "user_profiles",
    "user_preferences",
    "user_memories",
    "user_identities",
}


def _norm(stmt) -> str:
    return " ".join(str(stmt.compile(dialect=postgresql.dialect())).split())


def test_metadata_only_covers_app_tables():
    assert set(Base.metadata.tables) == APP_TABLES


def test_users_table_ddl():
    ddl = _norm(CreateTable(Base.metadata.tables["users"]))
    assert "CREATE TABLE users (" in ddl
    assert "id UUID NOT NULL" in ddl  # id is a UUID pk, not the legacy BIGINT IDENTITY
    assert "ck_users_valid_status" in ddl  # naming convention from app/db/base.py
    assert "uq_users_username" in ddl
    assert "TIMESTAMP WITH TIME ZONE DEFAULT now()" in ddl


def test_sessions_fk_and_columns():
    ddl = _norm(CreateTable(Base.metadata.tables["sessions"]))
    assert "CREATE TABLE sessions (" in ddl
    assert "REFERENCES users (id)" in ddl or "REFERENCES users(id)" in ddl
    assert "ON DELETE CASCADE" in ddl
    assert "token_hash TEXT NOT NULL" in ddl


def test_all_child_tables_cascade_from_users():
    for name in APP_TABLES - {"users", "sessions"}:
        ddl = _norm(CreateTable(Base.metadata.tables[name]))
        assert "REFERENCES users" in ddl, name
        assert "ON DELETE CASCADE" in ddl, name
