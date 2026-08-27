"""
To'lovlarni tasdiqlash/rad etish logikasi — TZ 6-7-bo'lim.

Momo Admin chekni ko'rib chiqib tasdiqlaydi yoki rad etadi:
    - hosting to'lovi tasdiqlansa -> bot PAUSED bo'lsa ACTIVE'ga qaytariladi
    - tarif oshirish to'lovi tasdiqlansa -> eski BotTariff deaktivatsiya qilinadi,
      yangisi (target tarif, muddat bilan) yaratiladi
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BotStatus, PaymentKind, PaymentStatus
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff
from app.models.payment import HostingPayment, Payment, TariffUpgrade
from app.models.tariff import Tariff
from app.models.user import User


class PaymentNotFoundError(Exception):
    pass


class NotAuthorizedError(Exception):
    pass


async def get_payment_or_raise(session: AsyncSession, payment_id: int) -> Payment:
    result = await session.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment is None:
        raise PaymentNotFoundError(f"To'lov topilmadi: {payment_id}")
    return payment


async def _require_momo_admin(session: AsyncSession, reviewer_telegram_id: int) -> User:
    result = await session.execute(select(User).where(User.telegram_id == reviewer_telegram_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_momo_admin:
        raise NotAuthorizedError("Faqat Momo Admin to'lovlarni tasdiqlashi mumkin.")
    return user


async def approve_payment(session: AsyncSession, payment_id: int, reviewer_telegram_id: int) -> Payment:
    reviewer = await _require_momo_admin(session, reviewer_telegram_id)
    payment = await get_payment_or_raise(session, payment_id)

    if payment.status != PaymentStatus.PENDING:
        raise ValueError(f"To'lov allaqachon ko'rib chiqilgan: status={payment.status}")

    payment.status = PaymentStatus.APPROVED
    payment.reviewed_by_admin_id = reviewer.id

    bot_result = await session.execute(select(BotModel).where(BotModel.id == payment.bot_id))
    bot_row = bot_result.scalar_one()

    if payment.kind == PaymentKind.HOSTING:
        hp_result = await session.execute(
            select(HostingPayment).where(HostingPayment.id == payment.reference_id)
        )
        hosting_payment = hp_result.scalar_one()
        hosting_payment.status = PaymentStatus.APPROVED

        if bot_row.status == BotStatus.PAUSED:
            bot_row.status = BotStatus.ACTIVE  # hosting to'lanmagani uchun to'xtatilgan edi (TZ 6.5)

    elif payment.kind == PaymentKind.TARIFF_UPGRADE:
        tu_result = await session.execute(
            select(TariffUpgrade).where(TariffUpgrade.id == payment.reference_id)
        )
        tariff_upgrade = tu_result.scalar_one()
        tariff_upgrade.status = PaymentStatus.APPROVED

        tariff_result = await session.execute(
            select(Tariff).where(Tariff.code == tariff_upgrade.tariff_code)
        )
        target_tariff = tariff_result.scalar_one()

        # Eski faol tarifni deaktivatsiya qilish
        old_result = await session.execute(
            select(BotTariff).where(BotTariff.bot_id == bot_row.id, BotTariff.is_active.is_(True))
        )
        for old_tariff in old_result.scalars().all():
            old_tariff.is_active = False

        started_at = datetime.date.today()
        expires_at = (
            started_at + datetime.timedelta(days=target_tariff.duration_days)
            if target_tariff.duration_days
            else None
        )
        session.add(
            BotTariff(
                bot_id=bot_row.id,
                tariff_code=target_tariff.code,
                started_at=started_at,
                expires_at=expires_at,
                is_active=True,
            )
        )

        if bot_row.status == BotStatus.SUSPENDED:
            bot_row.status = BotStatus.ACTIVE  # tarif tugab Start'ga tushirilgan edi (TZ 6.4)

    await session.commit()
    await session.refresh(payment)
    return payment


async def reject_payment(
    session: AsyncSession, payment_id: int, reviewer_telegram_id: int, reason: str | None
) -> Payment:
    reviewer = await _require_momo_admin(session, reviewer_telegram_id)
    payment = await get_payment_or_raise(session, payment_id)

    if payment.status != PaymentStatus.PENDING:
        raise ValueError(f"To'lov allaqachon ko'rib chiqilgan: status={payment.status}")

    payment.status = PaymentStatus.REJECTED
    payment.reviewed_by_admin_id = reviewer.id
    payment.rejection_reason = reason

    if payment.kind == PaymentKind.HOSTING:
        hp_result = await session.execute(
            select(HostingPayment).where(HostingPayment.id == payment.reference_id)
        )
        hosting_payment = hp_result.scalar_one()
        hosting_payment.status = PaymentStatus.REJECTED
    elif payment.kind == PaymentKind.TARIFF_UPGRADE:
        tu_result = await session.execute(
            select(TariffUpgrade).where(TariffUpgrade.id == payment.reference_id)
        )
        tariff_upgrade = tu_result.scalar_one()
        tariff_upgrade.status = PaymentStatus.REJECTED

    await session.commit()
    await session.refresh(payment)
    return payment
