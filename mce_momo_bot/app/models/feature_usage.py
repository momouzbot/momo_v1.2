"""
feature_usage_logs — modulga xos, Momo tarifidan MUSTAQIL kunlik limitlar
uchun umumiy (qayta ishlatiladigan) hisoblagich.

MUHIM FARQ: app/models/bot.py::EditLog — Momo tarifining umumiy tahrir
limitiga (Tariff.edit_limit_per_day — Start=3, Standard=5, Premium=10)
tegishli, botning HAMMA tahrirlari uchun BITTA umumiy hisoblagich.

FeatureUsageLog esa — har bir mijoz uchun BIR XIL (tarifdan qat'i nazar),
lekin FUNKSIYAGA XOS alohida kunlik limit kerak bo'lganda ishlatiladi —
masalan "kino qo'shish: 10/kun", "ommaviy xabar: 1/kun", "mavsum ochish:
2/kun". Har bir yangi funksiya uchun alohida jadval yozish shart emas —
`feature_key` orqali farqlanadi.
"""
from __future__ import annotations

import datetime

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, TimestampMixin


class FeatureUsageLog(Base, IDMixin, TimestampMixin):
    __tablename__ = "feature_usage_logs"
    __table_args__ = (
        UniqueConstraint("bot_id", "feature_key", "date", name="uq_bot_feature_date"),
    )

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)  # masalan "kino_qoshish"
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
