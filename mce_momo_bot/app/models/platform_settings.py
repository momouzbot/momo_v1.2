"""
platform_settings — Momo platformasining umumiy sozlamalari (hozircha
faqat to'lov rekvizitlari: karta raqami, egasi, qo'shimcha ko'rsatma).

Bitta yagona qator (singleton) sifatida ishlatiladi — har doim id=1.
Mijoz "To'lov cheki yuborish" yoki "Tarifni oshirish" bosganda, chek
so'ralishidan OLDIN shu ma'lumot ko'rsatiladi — aks holda mijoz qayerga
pul o'tkazishini bilmay qoladi.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TimestampMixin


class PlatformSettings(Base, IDMixin, TimestampMixin):
    __tablename__ = "platform_settings"

    payment_card_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_card_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Ixtiyoriy qo'shimcha ko'rsatma — masalan bank nomi yoki izoh
    payment_instructions: Mapped[str | None] = mapped_column(String(1000), nullable=True)
