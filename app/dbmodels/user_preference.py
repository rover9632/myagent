from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.dbmodels.user import User
from app.db.mixins import TimestampMixin


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "category",
            "preference_key",
            name="uq_user_preference_key",
        ),
        CheckConstraint(
            "source IN ('user_explicit', 'inferred', 'imported')",
            name="valid_source",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="valid_confidence",
        ),
        Index("ix_user_preferences_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    preference_key: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    preference_value: Mapped[Any] = mapped_column(
        JSONB, nullable=False
    )

    source: Mapped[str] = mapped_column(
        String(30),
        default="inferred",
        nullable=False,
    )

    confidence: Mapped[float | None] = mapped_column(Float)

    user: Mapped["User"] = relationship(
        back_populates="preferences"
    )
