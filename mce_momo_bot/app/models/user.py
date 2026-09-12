"""
users — Momo bot mijozlari (TZ 9-bo'lim, 8-bo'limdagi "Mijoz" roli).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TariffCode, TimestampMixin

if TYPE_CHECKING:
    from app.models.bot import Bot


class User(Base, IDMixin, TimestampMixin):
    """Momo platformasi mijozi (bot egasi)."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Momo botga /start bosgandagi qisqa ro'yxatdan o'tish oqimida so'raladi
    # (ism, telefon, ta'rif) — TZ 5-bo'lim yangilanishi.
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Ro'yxatdan o'tish oqimida (ism/telefon/ta'rif) tanlagan ta'rifi — bu shunchaki
    # mijozning niyati/afzalligi, haqiqiy bot tarifi (BotTariff) to'lov tasdiqlangach
    # belgilanadi. Start bo'lsa — bepul, darhol qo'llanadi.
    preferred_tariff_code: Mapped[TariffCode | None] = mapped_column(nullable=True)
    # Ism/telefon/ta'rif bosqichlari to'liq bosib o'tilganmi (True bo'lgach
    # /start endi qayta ro'yxatdan o'tishni so'ramaydi, to'g'ridan-to'g'ri
    # asosiy menyuni ko'rsatadi).
    registration_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Momo Admin — TZ 8-bo'lim: "Barcha botlarni ko'radi, to'lovlarni tasdiqlaydi"
    is_momo_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    bots: Mapped[list["Bot"]] = relationship(back_populates="owner")
