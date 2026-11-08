from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.dbmodels.user import User
from app.db.mixins import TimestampMixin


class UserProfile(Base, TimestampMixin):
    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(100)
    )
    avatar_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)

    locale: Mapped[str] = mapped_column(
        String(20), default="zh-CN", nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Shanghai", nullable=False
    )

    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    user: Mapped["User"] = relationship(
        back_populates="profile"
    )
