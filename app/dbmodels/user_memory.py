import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.dbmodels.user import User
from app.db.mixins import TimestampMixin


class UserMemory(Base, TimestampMixin):
    __tablename__ = "user_memories"

    __table_args__ = (
        CheckConstraint(
            "importance BETWEEN 0 AND 1",
            name="valid_importance",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="valid_confidence",
        ),
        CheckConstraint(
            "source IN ('user_explicit', 'inferred', 'imported')",
            name="valid_source",
        ),
        CheckConstraint(
            "status IN ('active', 'archived', 'deleted')",
            name="valid_status",
        ),
        Index(
            "ix_user_memories_user_type",
            "user_id",
            "memory_type",
        ),
        Index(
            "ix_user_memories_active",
            "user_id",
            "created_at",
            postgresql_where="status = 'active'",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    memory_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )

    importance: Mapped[float] = mapped_column(
        Float, default=0.5, nullable=False
    )
    confidence: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False
    )

    source: Mapped[str] = mapped_column(
        String(30), default="inferred", nullable=False
    )

    # 来源对话和消息，暂时不建立外键
    source_conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True)
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True)
    )

    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    user: Mapped["User"] = relationship(
        back_populates="memories"
    )
