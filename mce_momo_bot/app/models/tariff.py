"""
tariffs — tarif ta'riflari (bot_limit, edit_limit, narx, user_threshold), TZ 6.1-bo'lim.
Narxlar kodda qattiq yozilmaydi — shu jadvalda saqlanadi va admin panel orqali o'zgartiriladi.
"""
from __future__ import annotations

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TariffCode, TimestampMixin


class Tariff(Base, IDMixin, TimestampMixin):
    __tablename__ = "tariffs"

    code: Mapped[TariffCode] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    bot_limit: Mapped[int] = mapped_column(Integer, nullable=False)          # Start=1, Standard=2, Premium=7
    edit_limit_per_day: Mapped[int] = mapped_column(Integer, nullable=False)  # 2 / 4 / 10

    # Bir martalik tarifga o'tish narxi (Start uchun 0 — doimo bepul)
    upgrade_price: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    # Bazaviy oylik hosting narxi (bot boshiga), 1x koeffitsient uchun
    base_hosting_price: Mapped[Numeric] = mapped_column(Numeric(12, 2), nullable=False)

    # 1000 user chegarasi (TZ 6.3) — koeffitsient shu qiymat asosida hisoblanadi
    user_threshold: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)

    # Tarif muddati (kun hisobida). Start uchun NULL — muddatsiz.
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Standard/Premium = 180
