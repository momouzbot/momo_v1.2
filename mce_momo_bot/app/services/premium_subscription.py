"""
Premium obuna tizimi (KinoBotModule) — servis qatlami.

MUHIM: bu yerdagi pul mijozning (bot egasining) O'Z daromadi — Momo
to'lov tizimi (app/services/payments.py) bilan HECH QANDAY aloqasi yo'q,
Momo hech qanday ulush olmaydi.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import PaymentStatus
from app.models.bot import Bot as BotModel
from app.models.premium_subscription import PremiumSubscriber, PremiumSubscriptionPayment


class PremiumPaymentNotFoundError(Exception):
    pass


async def get_premium_settings(session: AsyncSession, bot_id: int) -> BotModel:
    result = await session.execute(select(BotModel).where(BotModel.id == bot_id))
    return result.scalar_one()


async def set_premium_settings(
    session: AsyncSession, bot_id: int, enabled: bool, price: float, duration_days: int
) -> BotModel:
    bot_row = await get_premium_settings(session, bot_id)
    bot_row.premium_subscription_enabled = enabled
    bot_row.premium_subscription_price = price
    bot_row.premium_subscription_duration_days = duration_days
    await session.commit()
    await session.refresh(bot_row)
    return bot_row


async def has_active_premium(session: AsyncSession, bot_id: int, telegram_user_id: int) -> bool:
    today = datetime.date.today()
    result = await session.execute(
        select(PremiumSubscriber).where(
            PremiumSubscriber.bot_id == bot_id,
            PremiumSubscriber.telegram_user_id == telegram_user_id,
            PremiumSubscriber.expires_at >= today,
        )
    )
    return result.scalar_one_or_none() is not None


async def get_premium_expiry(session: AsyncSession, bot_id: int, telegram_user_id: int) -> datetime.date | None:
    result = await session.execute(
        select(PremiumSubscriber).where(
            PremiumSubscriber.bot_id == bot_id, PremiumSubscriber.telegram_user_id == telegram_user_id
        )
    )
    sub = result.scalar_one_or_none()
    return sub.expires_at if sub else None


async def submit_premium_payment(
    session: AsyncSession, bot_id: int, telegram_user_id: int, amount: float, receipt_file_id: str
) -> PremiumSubscriptionPayment:
    payment = PremiumSubscriptionPayment(
        bot_id=bot_id,
        telegram_user_id=telegram_user_id,
        amount=amount,
        receipt_file_id=receipt_file_id,
        status=PaymentStatus.PENDING,
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


async def list_pending_premium_payments(session: AsyncSession, bot_id: int) -> list[PremiumSubscriptionPayment]:
    result = await session.execute(
        select(PremiumSubscriptionPayment)
        .where(PremiumSubscriptionPayment.bot_id == bot_id, PremiumSubscriptionPayment.status == PaymentStatus.PENDING)
        .order_by(PremiumSubscriptionPayment.created_at)
    )
    return list(result.scalars().all())


async def approve_premium_payment(session: AsyncSession, payment_id: int) -> PremiumSubscriptionPayment:
    """Obunani tasdiqlaydi va PremiumSubscriber.expires_at ni uzaytiradi
    (agar hali faol obuna bo'lsa — tugash sanasidan, aks holda bugundan
    boshlab hisoblanadi, shunday qilib mijoz vaqtidan yutqazmaydi)."""
    result = await session.execute(
        select(PremiumSubscriptionPayment).where(PremiumSubscriptionPayment.id == payment_id)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise PremiumPaymentNotFoundError(f"To'lov topilmadi: {payment_id}")
    if payment.status != PaymentStatus.PENDING:
        return payment  # allaqachon ko'rib chiqilgan — qayta ishlanmaydi

    bot_row = await get_premium_settings(session, payment.bot_id)
    today = datetime.date.today()

    sub_result = await session.execute(
        select(PremiumSubscriber).where(
            PremiumSubscriber.bot_id == payment.bot_id,
            PremiumSubscriber.telegram_user_id == payment.telegram_user_id,
        )
    )
    subscriber = sub_result.scalar_one_or_none()

    base_date = subscriber.expires_at if (subscriber and subscriber.expires_at >= today) else today
    new_expiry = base_date + datetime.timedelta(days=bot_row.premium_subscription_duration_days)

    if subscriber is None:
        session.add(
            PremiumSubscriber(
                bot_id=payment.bot_id, telegram_user_id=payment.telegram_user_id, expires_at=new_expiry
            )
        )
    else:
        subscriber.expires_at = new_expiry

    payment.status = PaymentStatus.APPROVED
    await session.commit()
    await session.refresh(payment)
    return payment


async def reject_premium_payment(session: AsyncSession, payment_id: int) -> PremiumSubscriptionPayment:
    result = await session.execute(
        select(PremiumSubscriptionPayment).where(PremiumSubscriptionPayment.id == payment_id)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise PremiumPaymentNotFoundError(f"To'lov topilmadi: {payment_id}")
    if payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.REJECTED
        await session.commit()
        await session.refresh(payment)
    return payment
