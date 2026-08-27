"""
game_settings, game_instances, game_players — TZ 4.5.4 va 9-bo'lim.
"""
from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TimestampMixin


class GameSettings(Base, IDMixin, TimestampMixin):
    """
    game_settings (bot_id, max_players, max_active_sessions, scheduler_interval).
    Cheklovlar kod ichida qattiq belgilanmaydi — admin panelda sozlanadi (TZ 4.5.4).
    """

    __tablename__ = "game_settings"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), unique=True, nullable=False)
    max_players: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_active_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scheduler_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GameInstance(Base, IDMixin, TimestampMixin):
    """game_instances — faol o'yin sessiyalari."""

    __tablename__ = "game_instances"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # guruh/dunyo identifikatori
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="waiting")  # waiting/running/finished
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)  # kecha/kunduz, raund va h.k.
    state: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # o'yin turiga xos qo'shimcha holat
    started_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)


class GamePlayer(Base, IDMixin, TimestampMixin):
    """game_players — o'yinchi holati/resurslari."""

    __tablename__ = "game_players"

    game_instance_id: Mapped[int] = mapped_column(
        ForeignKey("game_instances.id", ondelete="CASCADE"), nullable=False
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Mafia/Bunker uchun
    is_alive: Mapped[bool] = mapped_column(default=True, nullable=False)
    resources: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GOT uchun: oltin/oziq-ovqat/askar
