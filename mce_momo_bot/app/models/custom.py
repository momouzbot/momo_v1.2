"""
custom_commands, custom_buttons — CustomBotModule (konstruktor bot), TZ 4.6-bo'lim.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TimestampMixin


class CustomCommand(Base, IDMixin, TimestampMixin):
    """custom_commands (bot_id, buyruq, javob_matni, media_file_id)."""

    __tablename__ = "custom_commands"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    buyruq: Mapped[str] = mapped_column(String(64), nullable=False)  # masalan "/narxlar"
    javob_matni: Mapped[str | None] = mapped_column(String, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CustomButton(Base, IDMixin, TimestampMixin):
    """
    custom_buttons (bot_id, parent_id, matn, turi, target_command_id).
    Daraxtsimon tugmali menyu, chuqurligi cheklangan (masalan 3 daraja) — TZ 4.6.
    """

    __tablename__ = "custom_buttons"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("custom_buttons.id", ondelete="CASCADE"), nullable=True)
    matn: Mapped[str] = mapped_column(String(100), nullable=False)
    turi: Mapped[str] = mapped_column(String(50), nullable=False)  # masalan: "submenu" | "command_link"
    target_command_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_commands.id", ondelete="SET NULL"), nullable=True
    )
