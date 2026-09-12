"""
To'lov API'lari — TZ 7-bo'lim.

    POST /api/payments/hosting          — oylik hosting cheki yuborish
    POST /api/payments/tariff-upgrade   — tarif oshirish cheki yuborish
    POST /api/payments/{payment_id}/review — Momo Admin tasdiqlash/rad etish
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.schemas_payments import (
    PaymentResponse,
    ReviewPaymentRequest,
    SubmitHostingPaymentRequest,
    SubmitTariffUpgradeRequest,
)
from app.database import AsyncSessionLocal
from app.models.base import PaymentKind, PaymentStatus
from app.models.payment import HostingPayment, Payment, TariffUpgrade
from app.services.limits import (
    LimitExceededError,
    calculate_hosting_price,
    get_tariff_by_code,
    get_unique_user_count,
)
from app.services.payments import (
    NotAuthorizedError,
    PaymentNotFoundError,
    approve_payment,
    reject_payment,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _first_of_month(d: datetime.date) -> datetime.date:
    return d.replace(day=1)


@router.post("/hosting", response_model=PaymentResponse)
async def submit_hosting_payment(payload: SubmitHostingPaymentRequest) -> PaymentResponse:
    async with AsyncSessionLocal() as session:
        try:
            unique_users = await get_unique_user_count(session, payload.bot_id)
            amount = await calculate_hosting_price(session, payload.bot_id, unique_users)
        except LimitExceededError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        period_month = _first_of_month(datetime.date.today())

        # Shu oy uchun allaqachon kutilayotgan/tasdiqlangan to'lov bormi?
        existing = await session.execute(
            select(HostingPayment).where(
                HostingPayment.bot_id == payload.bot_id,
                HostingPayment.period_month == period_month,
                HostingPayment.status != PaymentStatus.REJECTED,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Bu oy uchun to'lov allaqachon yuborilgan.")

        hosting_payment = HostingPayment(
            bot_id=payload.bot_id, period_month=period_month, amount=amount, status=PaymentStatus.PENDING
        )
        session.add(hosting_payment)
        await session.flush()

        payment = Payment(
            bot_id=payload.bot_id,
            kind=PaymentKind.HOSTING,
            reference_id=hosting_payment.id,
            receipt_file_id=payload.receipt_file_id,
            status=PaymentStatus.PENDING,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)

        return PaymentResponse(
            payment_id=payment.id, bot_id=payment.bot_id, kind=payment.kind,
            status=payment.status, amount=float(amount),
        )


@router.post("/tariff-upgrade", response_model=PaymentResponse)
async def submit_tariff_upgrade_payment(payload: SubmitTariffUpgradeRequest) -> PaymentResponse:
    async with AsyncSessionLocal() as session:
        try:
            target_tariff = await get_tariff_by_code(session, payload.target_tariff)
        except LimitExceededError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        amount = float(target_tariff.upgrade_price)

        tariff_upgrade = TariffUpgrade(
            bot_id=payload.bot_id,
            tariff_code=payload.target_tariff,
            amount=amount,
            status=PaymentStatus.PENDING,
        )
        session.add(tariff_upgrade)
        await session.flush()

        payment = Payment(
            bot_id=payload.bot_id,
            kind=PaymentKind.TARIFF_UPGRADE,
            reference_id=tariff_upgrade.id,
            receipt_file_id=payload.receipt_file_id,
            status=PaymentStatus.PENDING,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)

        return PaymentResponse(
            payment_id=payment.id, bot_id=payment.bot_id, kind=payment.kind,
            status=payment.status, amount=amount,
        )


@router.post("/{payment_id}/review", response_model=PaymentResponse)
async def review_payment(payment_id: int, payload: ReviewPaymentRequest) -> PaymentResponse:
    async with AsyncSessionLocal() as session:
        try:
            if payload.approve:
                payment = await approve_payment(session, payment_id, payload.reviewed_by_telegram_id)
            else:
                payment = await reject_payment(
                    session, payment_id, payload.reviewed_by_telegram_id, payload.rejection_reason
                )
        except PaymentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except NotAuthorizedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return PaymentResponse(
            payment_id=payment.id, bot_id=payment.bot_id, kind=payment.kind,
            status=payment.status, amount=0.0,  # amount ma'lumoti alohida so'rov orqali olinadi
        )
