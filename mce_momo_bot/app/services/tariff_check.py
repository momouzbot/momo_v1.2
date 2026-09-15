"""
Tarif muddati nazorati — TZ 6.4-bo'lim (yangilangan: narx jadvali bo'yicha
imtiyoz kunlari + ortiqcha botlarni to'xtatish).

Standard/Premium tarif muddati tugaganda:
    1. Tarifning IMTIYOZ MUDDATI (grace_period_days) ham o'tgan bo'lsagina —
       o'sha BOT uchun tarif Start'ga tushiriladi (Standard uchun odatda 0
       kun — darhol; Premium uchun 30 kun — jadval bo'yicha).
    2. Shundan so'ng mijozning YANGI (pasaygan) bot limitidan ortiq bo'lgan
       botlari SUSPENDED holatiga o'tkaziladi — eng oldin yaratilgan botlar
       ustunlikka ega (ular faol qoladi), eng yangi qo'shilganlari to'xtaydi.

Bu qiymatlar (grace_period_days, bot_limit) admin panel orqali sozlanadi,
kodga mahkamlanmagan.

Markaziy scheduler orqali chaqiriladi (app/services/scheduler.py).
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.base import BotStatus, TariffCode
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff
from app.models.tariff import Tariff
from app.services.limits import get_owner_bot_limit

logger = logging.getLogger(__name__)


async def _suspend_excess_bots(session: AsyncSession, owner_id: int) -> None:
    """Mijozning yangi (pasaygan) limitidan ortiq bo'lgan botlarini SUSPENDED
    qiladi — eng oldin yaratilgan botlar ustunlikka ega (ular faol qoladi)."""
    limit = await get_owner_bot_limit(session, owner_id)

    result = await session.execute(
        select(BotModel)
        .where(BotModel.owner_id == owner_id, BotModel.status != BotStatus.DELETED)
        .order_by(BotModel.created_at.asc())
    )
    bots = result.scalars().all()

    for index, bot_row in enumerate(bots):
        if index < limit:
            continue  # limit doirasida — tegilmaydi
        if bot_row.status != BotStatus.SUSPENDED:
            bot_row.status = BotStatus.SUSPENDED
            logger.info(
                "Bot SUSPENDED holatiga o'tkazildi (owner limiti %s dan oshgan): bot_id=%s",
                limit, bot_row.telegram_bot_id,
            )


async def check_tariff_expirations() -> None:
    today = datetime.date.today()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BotTariff, Tariff)
            .join(Tariff, Tariff.code == BotTariff.tariff_code)
            .where(BotTariff.is_active.is_(True), BotTariff.expires_at.is_not(None))
        )
        rows = result.all()

        affected_owner_ids: set[int] = set()

        for old_tariff, tariff in rows:
            grace_deadline = old_tariff.expires_at + datetime.timedelta(days=tariff.grace_period_days)
            if grace_deadline >= today:
                continue  # muddat hali tugamagan yoki imtiyoz davrida

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
                "Tarif muddati (+ imtiyoz) tugadi, Start'ga tushirildi: bot_id=%s (avvalgi: %s)",
                old_tariff.bot_id, old_tariff.tariff_code,
            )

            bot_result = await session.execute(select(BotModel.owner_id).where(BotModel.id == old_tariff.bot_id))
            owner_id = bot_result.scalar_one_or_none()
            if owner_id is not None:
                affected_owner_ids.add(owner_id)

        # Yangi limitni to'g'ri hisoblash uchun yuqoridagi o'zgarishlar
        # (is_active=False, yangi Start qatori) avval bazaga aks etishi kerak.
        await session.flush()

        for owner_id in affected_owner_ids:
            await _suspend_excess_bots(session, owner_id)

        await session.commit()
