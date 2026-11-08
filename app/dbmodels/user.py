import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.dbmodels.session import Session
    from app.dbmodels.user_identity import UserIdentity
    from app.dbmodels.user_memory import UserMemory
    from app.dbmodels.user_preference import UserPreference
    from app.dbmodels.user_profile import UserProfile


class User(Base, TimestampMixin):
    __tablename__ = "users"

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled', 'locked', 'deleted')",
            name="valid_status",
        ),
        Index("ix_users_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True
    )
    phone: Mapped[str | None] = mapped_column(
        String(32), unique=True
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255)
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        server_default="active",
        nullable=False,
    )

    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_login_ip: Mapped[str | None] = mapped_column(INET)

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # 一对一
    profile: Mapped["UserProfile"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

    # 一对多
    preferences: Mapped[list["UserPreference"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    memories: Mapped[list["UserMemory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    identities: Mapped[list["UserIdentity"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


# Case-insensitive uniqueness without the citext extension (anti-impersonation);
# carried over from the retired hand-written baseline. Declared post-class
# because it needs the column object. Functional indexes are the classic
# autogenerate phantom-diff source -- read generated revisions before upgrading.
Index("ix_users_username_lower", func.lower(User.username), unique=True)
