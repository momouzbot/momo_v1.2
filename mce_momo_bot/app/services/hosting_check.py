"""
Oylik hosting nazorati — TZ 6.5-bo'lim.
Har oy boshida (yoki belgilangan muddatdan keyin) hosting to'lanmagan
botlarni PAUSED holatiga o'tkazadi va webhookni o'chiradi.

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
from app.services.telegram import delete_webhook

logger = logging.getLogger(__name__)


async def check_hosting_payments() -> None:
    """
    Joriy oy uchun tasdiqlangan hosting to'lovi bo'lmagan barcha faol
    botlarni PAUSED holatiga o'tkazadi (TZ 6.5: "hosting to'lanmasa bot
    to'xtatiladi").
    """
    period_month = datetime.date.today().replace(day=1)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotModel).where(BotModel.status == BotStatus.ACTIVE))
        active_bots = result.scalars().all()

        for bot_row in active_bots:
            hp_result = await session.execute(
                select(HostingPayment).where(
                    HostingPayment.bot_id == bot_row.id,
                    HostingPayment.period_month == period_month,
                    HostingPayment.status == PaymentStatus.APPROVED,
                )
            )
            if hp_result.scalar_one_or_none() is not None:
                continue  # to'langan — davom etaveradi

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
