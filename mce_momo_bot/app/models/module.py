"""
modules — mavjud modullar ro'yxati (TZ 9-bo'lim, 4.7-bo'lim: kengaytiriladiganlik).
Yangi bot turi qo'shish shu jadvalga yozuv + yangi modul klassi orqali amalga oshadi.
"""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, ModuleType, TimestampMixin


class Module(Base, IDMixin, TimestampMixin):
    __tablename__ = "modules"

    code: Mapped[ModuleType] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # foydalanuvchiga ko'rinadimi
