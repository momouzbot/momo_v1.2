"""
movies — KinoBotModule uchun kino ma'lumotlari (TZ 4.3-bo'lim).
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TimestampMixin


class Movie(Base, IDMixin, TimestampMixin):
    __tablename__ = "movies"
    __table_args__ = (UniqueConstraint("bot_id", "code", name="uq_bot_movie_code"),)

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)

    code: Mapped[str] = mapped_column(String(32), nullable=False)  # foydalanuvchi qidiradigan kod, masalan "1024"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="video")  # video | document
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Telegram file_id

    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
