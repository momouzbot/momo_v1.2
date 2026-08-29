"""
appeals — MurojaatModule uchun murojaatlar jadvali (TZ 4.2-bo'lim).
"""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AppealCategory, AppealStatus, Base, IDMixin, TimestampMixin

# AppealStatus va AppealCategory endi app.models.base ichida aniqlangan
# (type_annotation_map orqali PostgreSQL enum nomini to'g'ri bog'lash uchun),
# shu sababli bu yerda faqat qayta eksport qilinadi — mavjud import
# joylaridagi `from app.models.appeal import AppealStatus` kabi kodlar
# buzilmasligi uchun.
__all__ = ["Appeal", "AppealStatus", "AppealCategory"]


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
