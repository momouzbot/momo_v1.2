"""
hosting_payments, tariff_upgrades, payments — TZ 7-bo'lim (to'lov jarayoni)
va 9-bo'lim (jadval ro'yxati).
"""
from __future__ import annotations

import datetime

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, PaymentKind, PaymentStatus, TariffCode, TimestampMixin


class HostingPayment(Base, IDMixin, TimestampMixin):
    """hosting_payments — oylik hosting to'lovlari (bot_id, oy, summa, holat)."""

    __tablename__ = "hosting_payments"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    period_month: Mapped[datetime.date] = mapped_column(Date, nullable=False)  # oyning 1-sanasi bilan belgilanadi
    amount: Mapped[Numeric] = mapped_column(Numeric(12, 2), nullable=False)     # 6.3-formula bo'yicha hisoblangan
    status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.PENDING, nullable=False)


class TariffUpgrade(Base, IDMixin, TimestampMixin):
    """tariff_upgrades — bir martalik tarif o'tish to'lovlari (bot_id, tarif turi, summa, sana)."""

    __tablename__ = "tariff_upgrades"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    tariff_code: Mapped[TariffCode] = mapped_column(nullable=False)
    amount: Mapped[Numeric] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.PENDING, nullable=False)


class Payment(Base, IDMixin, TimestampMixin):
    """
    payments — umumiy to'lov cheklari va tasdiqlash holati (TZ 7-bo'lim).
    hosting_payments / tariff_upgrades yozuviga bog'lanadi, chek screenshot'ini
    va admin tasdig'ini saqlaydi.
    """

    __tablename__ = "payments"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[PaymentKind] = mapped_column(nullable=False)

    # Tegishli hosting_payments.id yoki tariff_upgrades.id (kind ga qarab)
    reference_id: Mapped[int | None] = mapped_column(nullable=True)

    receipt_file_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Telegram file_id (screenshot)
    status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.PENDING, nullable=False)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
