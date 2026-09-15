"""
To'lov API'lari — TZ 7-bo'lim.

    POST /api/payments/hosting          — oylik hosting cheki yuborish
    POST /api/payments/tariff-upgrade   — tarif oshirish cheki yuborish
    POST /api/payments/{payment_id}/review — Momo Admin tasdiqlash/rad etish

MUHIM: to'lov YARATISH logikasi (validatsiya + HostingPayment/TariffUpgrade/Payment
yozuvlarini yaratish) app/services/payments.py ga ko'chirilgan — shu orqali Momo
bot ham (mijoz botda chek yuborganda) aynan shu funksiyalarni chaqiradi, kod ikki
joyda takrorlanmaydi.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas_payments import (
    PaymentResponse,
    ReviewPaymentRequest,
    SubmitHostingPaymentRequest,
    SubmitTariffUpgradeRequest,
)
from app.api.security import require_api_key
from app.database import AsyncSessionLocal
from app.services.limits import LimitExceededError
from app.services.payments import (
    HostingPaymentAlreadyExistsError,
    NotAuthorizedError,
    PaymentNotFoundError,
    approve_payment,
    reject_payment,
    submit_hosting_payment,
    submit_tariff_upgrade,
)

router = APIRouter(prefix="/api/payments", tags=["payments"], dependencies=[Depends(require_api_key)])


@router.post("/hosting", response_model=PaymentResponse)
async def submit_hosting_payment_endpoint(payload: SubmitHostingPaymentRequest) -> PaymentResponse:
    async with AsyncSessionLocal() as session:
        try:
            payment, amount = await submit_hosting_payment(
                session, payload.bot_id, payload.billing_period, payload.receipt_file_id
            )
        except LimitExceededError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HostingPaymentAlreadyExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return PaymentResponse(
            payment_id=payment.id, bot_id=payment.bot_id, kind=payment.kind,
            status=payment.status, amount=amount,
        )


@router.post("/tariff-upgrade", response_model=PaymentResponse)
async def submit_tariff_upgrade_endpoint(payload: SubmitTariffUpgradeRequest) -> PaymentResponse:
    async with AsyncSessionLocal() as session:
        try:
            payment, amount = await submit_tariff_upgrade(
                session, payload.bot_id, payload.target_tariff, payload.receipt_file_id
            )
        except LimitExceededError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
