"""
bot_sub_admins — bot egasi tayinlagan yordamchi moderatorlar (TZ: "kinobot
moduli yakuniy tahrir rejasi" — umumiy/core funksiya, barcha modullarda
ishlaydi).

Sub-adminlar OWNER bilan bir xil huquqqa ega KONTENT boshqaruvida (masalan
kino qo'shish/o'chirish, murojaatlarga javob berish) — lekin bot sozlamalari
(majburiy kanal, ommaviy xabar) va sub-adminlarni boshqarishning O'ZI faqat
haqiqiy egaga (owner) tegishli — app/services/ownership.py::is_bot_owner
shu ikkovini farqlaydi.

Qat'iy limit: bot boshiga MAKSIMUM 3 ta sub-admin
(app/services/sub_admins.py::SUB_ADMIN_LIMIT).
"""
from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin


class BotSubAdmin(Base, IDMixin):
    __tablename__ = "bot_sub_admins"
    __table_args__ = (UniqueConstraint("bot_id", "telegram_user_id", name="uq_bot_sub_admin"),)

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Qo'shilgan paytdagi ism — snapshot sifatida saqlanadi (ro'yxatda
    # ko'rsatish uchun; Telegram API orqali keyin qayta so'rab bo'lmaydi).
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    added_by_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
