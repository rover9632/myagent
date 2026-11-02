"""SQLAlchemy Core metadata: single source of truth for the users/sessions schema.

Alembic autogenerates revisions from this module (see alembic/env.py). The
checkpoint* tables are intentionally NOT here -- they belong to
AsyncPostgresSaver.setup() and its own checkpoint_migrations ledger.
Runtime code keeps using raw psycopg SQL; this module exists for migrations only.

Heads-up for future edits: the functional index below (lower(username)) and the
IDENTITY column are the constructs most likely to produce phantom diffs from
`alembic revision --autogenerate`. Always read a generated revision before
running `alembic upgrade head`.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
    sa.Column("username", sa.Text, nullable=False),
    sa.Column("password_hash", sa.Text, nullable=False),
    sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Index("users_username_uidx", "username", unique=True),
)

# Case-insensitive uniqueness without the citext extension (anti-impersonation).
# Defined post-table because it needs the column object; name must stay
# byte-identical to the legacy index or autogenerate proposes drop+create.
sa.Index("users_username_lower_uidx", sa.func.lower(users.c.username), unique=True)

sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("token_hash", sa.Text, primary_key=True),
    sa.Column(
        "user_id",
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Index("sessions_expires_at_idx", "expires_at"),
)
