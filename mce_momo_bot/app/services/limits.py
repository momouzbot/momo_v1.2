"""
Tarif/limit tizimi — TZ 6-bo'lim.
Bot soni limiti va kunlik tahrirlash limiti shu yerda tekshiriladi.
Kunlik hisob har kecha 00:00 (Toshkent) da reset qilinadi — sana bo'yicha
alohida qator (edit_logs.date) orqali tabiiy ravishda amalga oshadi.
"""
from __future__ import annotations

import datetime

import pytz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff, EditLog
from app.models.tariff import Tariff

TASHKENT_TZ = pytz.timezone("Asia/Tashkent")


class LimitExceededError(Exception):
    pass


def today_tashkent() -> datetime.date:
    return datetime.datetime.now(TASHKENT_TZ).date()


async def get_tariff_by_code(session: AsyncSession, code) -> Tariff:
    result = await session.execute(select(Tariff).where(Tariff.code == code))
    tariff = result.scalar_one_or_none()
    if tariff is None:
        raise LimitExceededError(f"Tarif topilmadi: {code}")
    return tariff


async def get_active_tariff(session: AsyncSession, bot_id: int) -> Tariff:
    result = await session.execute(
        select(Tariff)
        .join(BotTariff, BotTariff.tariff_code == Tariff.code)
        .where(BotTariff.bot_id == bot_id, BotTariff.is_active.is_(True))
        .limit(1)
    )
    tariff = result.scalar_one_or_none()
    if tariff is None:
        raise LimitExceededError(f"Bot uchun faol tarif topilmadi: bot_id={bot_id}")
    return tariff


async def check_bot_limit(session: AsyncSession, owner_id: int, tariff: Tariff) -> None:
    """Mijozning faol botlari soni tarif bot_limit'idan oshmasligini tekshiradi (TZ 6.1)."""
    result = await session.execute(
        select(func.count()).select_from(BotModel).where(BotModel.owner_id == owner_id)
    )
    active_count = result.scalar_one()
    if active_count >= tariff.bot_limit:
        raise LimitExceededError(
            f"Bot limiti to'lgan: {active_count}/{tariff.bot_limit} (tarif: {tariff.code})"
        )


async def check_and_increment_edit_limit(session: AsyncSession, bot_id: int) -> None:
    """
    Yangi funksional panel/modul elementi qo'shishdan oldin chaqiriladi (TZ 6.2).
    Limitga yetgan bo'lsa LimitExceededError ko'taradi, aks holda hisoblagichni +1 qiladi.
    """
    tariff = await get_active_tariff(session, bot_id)
    today = today_tashkent()

    result = await session.execute(
        select(EditLog).where(EditLog.bot_id == bot_id, EditLog.date == today)
    )
    log_row = result.scalar_one_or_none()

    current_count = log_row.count if log_row else 0
    if current_count >= tariff.edit_limit_per_day:
        raise LimitExceededError(
            f"Kunlik tahrirlash limiti tugagan: {current_count}/{tariff.edit_limit_per_day}"
        )

    if log_row is None:
        session.add(EditLog(bot_id=bot_id, date=today, count=1))
    else:
        log_row.count = current_count + 1

    await session.commit()


async def calculate_hosting_price(session: AsyncSession, bot_id: int, unique_user_count: int) -> float:
    """
    1000 user chegarasi formulasi (TZ 6.3):
        koeffitsient = floor(user_soni / 1000) + 1
        narx = base_hosting_price * koeffitsient
    """
    tariff = await get_active_tariff(session, bot_id)
    coefficient = (unique_user_count // tariff.user_threshold) + 1
    return float(tariff.base_hosting_price) * coefficient


async def get_unique_user_count(session: AsyncSession, bot_id: int) -> int:
    """
    Noyob foydalanuvchilar soni (TZ 6.3):
        - Momo o'zi hostinglaydigan botlar uchun — bot_users jadvalidan hisoblanadi
        - Tashqi hostingdagi botlar uchun (masalan GOT Game) — bot o'zi hisobot
          bergan `external_user_count` qiymati ishlatiladi (bot_users bo'sh
          qoladi, chunki update'lar Momo dispatcheriga umuman kelmaydi)
    """
    from app.models.bot import Bot as BotModel
    from app.models.bot import BotUser

    bot_result = await session.execute(select(BotModel).where(BotModel.id == bot_id))
    bot_row = bot_result.scalar_one_or_none()
    if bot_row is None:
        raise LimitExceededError(f"Bot topilmadi: bot_id={bot_id}")

    if bot_row.is_externally_hosted:
        return bot_row.external_user_count

    result = await session.execute(
        select(func.count()).select_from(BotUser).where(BotUser.bot_id == bot_id)
    )
    return result.scalar_one()
