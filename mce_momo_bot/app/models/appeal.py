"""
appeals — MurojaatModule uchun murojaatlar jadvali (TZ 4.2-bo'lim).
"""
from __future__ import annotations

import enum

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TimestampMixin


class AppealStatus(str, enum.Enum):
    NEW = "new"              # yangi, hali javob berilmagan
    IN_PROGRESS = "in_progress"  # admin ko'rib chiqmoqda
    ANSWERED = "answered"    # javob berilgan
    CLOSED = "closed"        # yopilgan


class AppealCategory(str, enum.Enum):
    TECHNICAL = "technical"
    FINANCIAL = "financial"
    GENERAL = "general"


class Appeal(Base, IDMixin, TimestampMixin):
    """Bitta foydalanuvchi murojaati (bot_id bo'yicha izolyatsiya qilingan)."""

    __tablename__ = "appeals"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    category: Mapped[AppealCategory] = mapped_column(default=AppealCategory.GENERAL, nullable=False)
    status: Mapped[AppealStatus] = mapped_column(default=AppealStatus.NEW, nullable=False)

    message_text: Mapped[str] = mapped_column(String, nullable=False)
    admin_reply_text: Mapped[str | None] = mapped_column(String, nullable=True)

    # Admin guruhida forward qilingan xabarning ID'si — javobni bog'lash uchun
    forwarded_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
