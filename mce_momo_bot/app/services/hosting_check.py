"""
Hosting nazorati — TZ 6.5-bo'lim (yangilangan: haftalik/oylik davr modeli).
Bugungi kunni qamrab oladigan tasdiqlangan hosting to'lovi bo'lmagan barcha
faol botlarni PAUSED holatiga o'tkazadi va webhookni o'chiradi.

Har bir bot mustaqil ravishda haftalik yoki oylik to'lashni tanlaydi — shu
sababli "joriy davr" botdan botga farq qiladi; buni aniqlash uchun har bir
faol botning eng so'nggi hosting to'lovi(lari) tekshiriladi.

Markaziy scheduler orqali chaqiriladi (app/services/scheduler.py).
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import BotStatus, PaymentStatus
from app.models.bot import Bot as BotModel
from app.models.payment import HostingPayment
from app.services.crypto import decrypt_token
from app.services.payments import hosting_period_end
from app.services.telegram import delete_webhook

logger = logging.getLogger(__name__)


async def check_hosting_payments() -> None:
    """
    Bugungi kunni qamrab oladigan tasdiqlangan (APPROVED) hosting to'lovi
    bo'lmagan barcha faol botlarni PAUSED holatiga o'tkazadi.
    """
    today = datetime.date.today()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotModel).where(BotModel.status == BotStatus.ACTIVE))
        active_bots = result.scalars().all()

        for bot_row in active_bots:
            hp_result = await session.execute(
                select(HostingPayment).where(
                    HostingPayment.bot_id == bot_row.id,
                    HostingPayment.status == PaymentStatus.APPROVED,
                )
            )
            is_covered = any(
                hp.period_start <= today < hosting_period_end(hp.period_start, hp.billing_period)
                for hp in hp_result.scalars().all()
            )
            if is_covered:
                continue  # shu davr uchun to'langan — davom etaveradi

            bot_row.status = BotStatus.PAUSED
            try:
                token = decrypt_token(bot_row.token_encrypted)
                await delete_webhook(token)
            except Exception:
                logger.exception("Webhookni o'chirishda xato: bot_id=%s", bot_row.telegram_bot_id)

            logger.info(
                "Bot PAUSED holatiga o'tkazildi (hosting to'lanmagan): bot_id=%s",
                bot_row.telegram_bot_id,
            )

        await session.commit()
