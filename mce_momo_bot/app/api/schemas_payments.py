"""
To'lov API'lari uchun Pydantic sxemalari — TZ 7-bo'lim.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.base import PaymentKind, PaymentStatus, TariffCode


class SubmitHostingPaymentRequest(BaseModel):
    bot_id: int
    receipt_file_id: str = Field(..., description="Telegram file_id — chek screenshot")


class SubmitTariffUpgradeRequest(BaseModel):
    bot_id: int
    target_tariff: TariffCode
    receipt_file_id: str = Field(..., description="Telegram file_id — chek screenshot")


class PaymentResponse(BaseModel):
    payment_id: int
    bot_id: int
    kind: PaymentKind
    status: PaymentStatus
    amount: float


class ReviewPaymentRequest(BaseModel):
    approve: bool
    rejection_reason: str | None = None
    reviewed_by_telegram_id: int = Field(..., description="Tasdiqlovchi Momo Admin'ning Telegram ID'si")
