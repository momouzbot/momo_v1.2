"""
broadcast_logs — ommaviy xabar yuborish tarixi (TZ: "kinobot moduli yakuniy
tahrir rejasi" — umumiy/core funksiya, barcha modullarda ishlaydi).

Har bir yuborilgan ommaviy xabar uchun bitta yozuv — Momo bot orqali
"Ommaviy xabar statistikasini ko'rish" imkoniyati shu yerdan o'qiydi.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TimestampMixin


class BroadcastLog(Base, IDMixin, TimestampMixin):
    __tablename__ = "broadcast_logs"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    sent_by_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
