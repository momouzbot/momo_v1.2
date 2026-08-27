"""
Tarif muddati nazorati — TZ 6.4-bo'lim.
Standard/Premium tarif muddati (180 kun) tugagan botlarni avtomatik
Start tarifiga tushiradi.
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import TariffCode
from app.models.bot import BotTariff

logger = logging.getLogger(__name__)


async def check_tariff_expirations() -> None:
    today = datetime.date.today()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BotTariff).where(
                BotTariff.is_active.is_(True),
                BotTariff.expires_at.is_not(None),
                BotTariff.expires_at < today,
            )
        )
        expired = result.scalars().all()

        for old_tariff in expired:
            old_tariff.is_active = False
            session.add(
                BotTariff(
                    bot_id=old_tariff.bot_id,
                    tariff_code=TariffCode.START,
                    started_at=today,
                    expires_at=None,
                    is_active=True,
                )
            )
            logger.info(
                "Tarif muddati tugadi, Start'ga tushirildi: bot_id=%s (avvalgi: %s)",
                old_tariff.bot_id, old_tariff.tariff_code,
            )
            # Eslatma: bot_limit yangi (Start=1) qiymatga tushishi mumkin — agar
            # mijozning bir nechta boti bo'lsa, ortiqcha botlar bilan nima
            # qilish (PAUSED qilish yoki admin qo'lda hal qilishi) TODO —
            # biznes qoidasi aniqlashtirilishi kerak.

        await session.commit()
