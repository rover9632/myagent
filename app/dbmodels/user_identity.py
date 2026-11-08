from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.dbmodels.user import User
from app.db.mixins import TimestampMixin


class UserIdentity(Base, TimestampMixin):
    __tablename__ = "user_identities"

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_identity_provider_user",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    provider_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    email: Mapped[str | None] = mapped_column(String(255))

    user: Mapped["User"] = relationship(
        back_populates="identities"
    )
