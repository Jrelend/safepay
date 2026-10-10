"""Platform-wide safety policy (a single row, changed only by the schema owner)."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlatformPolicy(Base):
    """Exactly one row (``id = true``).

    ``auto_release_enabled`` is **false** in Beta v0.1: an expired inspection window
    never releases escrow by itself. Only the buyer's confirmation or an admin decision
    can. The SYSTEM transition function refuses AUTO_RELEASE while this is false, and
    no runtime role may UPDATE this table (only the owner, via ``app.cli``).
    """

    __tablename__ = "platform_policy"
    __table_args__ = (CheckConstraint("id", name="single_row"),)

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True, server_default=text("true"))
    auto_release_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str] = mapped_column(String(200), server_default="")
