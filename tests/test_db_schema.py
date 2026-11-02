"""Pin app/db_schema.py metadata to the DDL the Alembic baseline actually runs.

Pure in-memory compilation (postgresql dialect) — no PostgreSQL needed. These
assertions are the contract that keeps `alembic revision --autogenerate` from
silently diverging from the schema users' databases already have.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db_schema import metadata, sessions, users


def _norm(stmt) -> str:
    return " ".join(str(stmt.compile(dialect=postgresql.dialect())).split())


def test_metadata_only_covers_app_tables():
    assert set(metadata.tables) == {"users", "sessions"}


def test_users_table_ddl():
    ddl = _norm(CreateTable(users))
    assert "CREATE TABLE users (" in ddl
    assert "GENERATED ALWAYS AS IDENTITY" in ddl
    assert "TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in ddl  # == TIMESTAMPTZ
    assert "password_hash TEXT NOT NULL" in ddl


def test_users_indexes():
    idx = {_norm(CreateIndex(i)) for i in users.indexes}
    assert any("users_username_uidx" in s and "UNIQUE" in s and "(username)" in s for s in idx)
    assert any(
        "users_username_lower_uidx" in s and "UNIQUE" in s and "lower(username)" in s for s in idx
    )


def test_sessions_table_ddl():
    ddl = _norm(CreateTable(sessions))
    assert "CREATE TABLE sessions (" in ddl
    assert "ON DELETE CASCADE" in ddl
    assert "REFERENCES users (id)" in ddl or "REFERENCES users(id)" in ddl
    assert "token_hash TEXT NOT NULL" in ddl  # primary key column


def test_sessions_expires_at_index():
    idx = {_norm(CreateIndex(i)) for i in sessions.indexes}
    assert any(
        s.startswith("CREATE INDEX sessions_expires_at_idx") and "expires_at" in s for s in idx
    )
    assert not any("UNIQUE" in s for s in idx)  # plain index, matches legacy DDL
