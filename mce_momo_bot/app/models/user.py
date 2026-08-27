"""
users — Momo bot mijozlari (TZ 9-bo'lim, 8-bo'limdagi "Mijoz" roli).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IDMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.bot import Bot


class User(Base, IDMixin, TimestampMixin):
    """Momo platformasi mijozi (bot egasi)."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Momo Admin — TZ 8-bo'lim: "Barcha botlarni ko'radi, to'lovlarni tasdiqlaydi"
    is_momo_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    bots: Mapped[list["Bot"]] = relationship(back_populates="owner")
