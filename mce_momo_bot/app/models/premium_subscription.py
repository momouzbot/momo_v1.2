"""
Premium obuna tizimi (KinoBotModule) — mijozning O'Z tomoshabinlari
to'laydigan ichki xizmat. Momo'ning to'lov tizimidan (app/models/payment.py)
BUTUNLAY ALOHIDA — bu yerdagi pul mijozning (bot egasining) shaxsiy
daromadi, Momo hech qanday ulush olmaydi va aralashmaydi.

    PremiumSubscriber       — kimning obunasi qachon tugashi
    PremiumSubscriptionPayment — obuna uchun yuborilgan chek va uning holati
"""
from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, PaymentStatus, TimestampMixin


class PremiumSubscriber(Base, IDMixin, TimestampMixin):
    __tablename__ = "premium_subscribers"
    __table_args__ = (UniqueConstraint("bot_id", "telegram_user_id", name="uq_premium_subscriber"),)

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime.date] = mapped_column(Date, nullable=False)


class PremiumSubscriptionPayment(Base, IDMixin, TimestampMixin):
    __tablename__ = "premium_subscription_payments"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Numeric] = mapped_column(Numeric(12, 2), nullable=False)
    receipt_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.PENDING, nullable=False)
