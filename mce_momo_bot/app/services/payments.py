"""
To'lovlarni yaratish, tasdiqlash/rad etish logikasi — TZ 6-7-bo'lim.

submit_hosting_payment / submit_tariff_upgrade — mijoz chek yuborganda chaqiriladi
(ilgari bu logika faqat app/api/payments.py ichida bo'lgan va botda ishlatib
bo'lmasdi; endi ikkalasi — ham API, ham Momo bot — shu yerdan foydalanadi).

approve_payment / reject_payment — Momo Admin chekni ko'rib chiqqanda:
    - hosting to'lovi tasdiqlansa -> bot PAUSED bo'lsa ACTIVE'ga qaytariladi
    - tarif oshirish to'lovi tasdiqlansa -> eski BotTariff deaktivatsiya qilinadi,
      yangisi (target tarif, muddat bilan) yaratiladi
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BotStatus, PaymentKind, PaymentStatus, TariffCode
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff
from app.models.payment import HostingPayment, Payment, TariffUpgrade
from app.models.tariff import Tariff
from app.models.user import User
from app.services.limits import calculate_hosting_price, get_tariff_by_code, get_unique_user_count


class PaymentNotFoundError(Exception):
    pass


class NotAuthorizedError(Exception):
    pass


class HostingPaymentAlreadyExistsError(Exception):
    """Shu oy uchun allaqachon PENDING/APPROVED hosting to'lovi mavjud."""


def _first_of_month(d: datetime.date) -> datetime.date:
    return d.replace(day=1)


async def hosting_payment_status_this_month(session: AsyncSession, bot_id: int) -> PaymentStatus | None:
    """Joriy oy uchun so'nggi hosting to'lovi holati (REJECTED bo'lsa ham qaytariladi,
    chunki mijozga "rad etilgan, qayta yuboring" deb ko'rsatish uchun kerak)."""
    period_month = _first_of_month(datetime.date.today())
    result = await session.execute(
        select(HostingPayment)
        .where(HostingPayment.bot_id == bot_id, HostingPayment.period_month == period_month)
        .order_by(HostingPayment.created_at.desc())
    )
    hosting_payment = result.scalars().first()
    return hosting_payment.status if hosting_payment else None


async def submit_hosting_payment(
    session: AsyncSession, bot_id: int, receipt_file_id: str
) -> tuple[Payment, float]:
    """Oylik hosting cheki yuboriladi. Shu oy uchun PENDING/APPROVED to'lov
    mavjud bo'lsa HostingPaymentAlreadyExistsError ko'taradi (REJECTED bo'lsa
    qayta yuborishga ruxsat beriladi)."""
    unique_users = await get_unique_user_count(session, bot_id)
    amount = await calculate_hosting_price(session, bot_id, unique_users)

    period_month = _first_of_month(datetime.date.today())

    existing = await session.execute(
        select(HostingPayment).where(
            HostingPayment.bot_id == bot_id,
            HostingPayment.period_month == period_month,
            HostingPayment.status != PaymentStatus.REJECTED,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HostingPaymentAlreadyExistsError("Bu oy uchun to'lov allaqachon yuborilgan.")

    hosting_payment = HostingPayment(
        bot_id=bot_id, period_month=period_month, amount=amount, status=PaymentStatus.PENDING
    )
    session.add(hosting_payment)
    await session.flush()

    payment = Payment(
        bot_id=bot_id,
        kind=PaymentKind.HOSTING,
        reference_id=hosting_payment.id,
        receipt_file_id=receipt_file_id,
        status=PaymentStatus.PENDING,
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment, amount


async def submit_tariff_upgrade(
    session: AsyncSession, bot_id: int, target_tariff_code: TariffCode, receipt_file_id: str
) -> tuple[Payment, float]:
    """Tarif oshirish cheki yuboriladi (bir martalik to'lov)."""
    target_tariff = await get_tariff_by_code(session, target_tariff_code)
    amount = float(target_tariff.upgrade_price)

    tariff_upgrade = TariffUpgrade(
        bot_id=bot_id, tariff_code=target_tariff_code, amount=amount, status=PaymentStatus.PENDING
    )
    session.add(tariff_upgrade)
    await session.flush()

    payment = Payment(
        bot_id=bot_id,
        kind=PaymentKind.TARIFF_UPGRADE,
        reference_id=tariff_upgrade.id,
        receipt_file_id=receipt_file_id,
        status=PaymentStatus.PENDING,
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment, amount


async def get_payment_or_raise(session: AsyncSession, payment_id: int) -> Payment:
    result = await session.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment is None:
        raise PaymentNotFoundError(f"To'lov topilmadi: {payment_id}")
    return payment


async def list_pending_payments(session: AsyncSession) -> list[Payment]:
    """Admin panel — "💳 To'lovlar" bo'limida ko'rsatiladigan PENDING ro'yxati."""
    result = await session.execute(
        select(Payment).where(Payment.status == PaymentStatus.PENDING).order_by(Payment.created_at)
    )
    return list(result.scalars().all())


async def get_payment_with_context(session: AsyncSession, payment_id: int) -> tuple[Payment, BotModel, User]:
    """To'lovni bot va mijoz (owner) ma'lumotlari bilan birga qaytaradi —
    admin panelda batafsil ko'rsatish uchun."""
    payment = await get_payment_or_raise(session, payment_id)

    bot_result = await session.execute(select(BotModel).where(BotModel.id == payment.bot_id))
    bot_row = bot_result.scalar_one()

    owner_result = await session.execute(select(User).where(User.id == bot_row.owner_id))
    owner = owner_result.scalar_one()

    return payment, bot_row, owner


async def get_payment_amount_and_label(session: AsyncSession, payment: Payment) -> tuple[float, str]:
    """To'lov turiga qarab (hosting/tarif oshirish) summa va inson o'qiy oladigan
    tavsifni qaytaradi — Payment jadvalining o'zida summa saqlanmaydi, u
    reference_id orqali HostingPayment/TariffUpgrade'dan olinadi."""
    if payment.kind == PaymentKind.HOSTING:
        result = await session.execute(select(HostingPayment).where(HostingPayment.id == payment.reference_id))
        hosting_payment = result.scalar_one()
        return float(hosting_payment.amount), "Oylik hosting to'lovi"

    result = await session.execute(select(TariffUpgrade).where(TariffUpgrade.id == payment.reference_id))
    tariff_upgrade = result.scalar_one()

    tariff_result = await session.execute(select(Tariff).where(Tariff.code == tariff_upgrade.tariff_code))
    tariff = tariff_result.scalar_one_or_none()
    tariff_name = tariff.name if tariff else tariff_upgrade.tariff_code.value

    return float(tariff_upgrade.amount), f"Tarif oshirish → {tariff_name}"


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
