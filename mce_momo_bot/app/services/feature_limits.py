"""
Modulga xos, Momo tarifidan MUSTAQIL kunlik limitlar — "kinobot moduli
yakuniy tahrir rejasi" bo'yicha (masalan "kino qo'shish: 10/kun", "ommaviy
xabar: 1/kun"). Har bir mijoz uchun BIR XIL — tarifga (Start/Standard/
Premium) qarab farq qilmaydi, faqat funksiyaga qarab farq qiladi.

MUHIM FARQ: bu — app/services/limits.py::check_and_increment_edit_limit'dan
BOSHQA narsa. U — Tariff.edit_limit_per_day orqali (tarifga qarab
o'zgaruvchi) UMUMIY tahrir hisoblagichi. Bu yerdagi funksiya esa — har bir
alohida funksiya ("feature_key") uchun mustaqil, doimiy sonli limit.

Yangi funksiya qo'shish uchun boshqa jadval/migratsiya kerak emas — shunchaki
yangi `feature_key` va limit soni bilan chaqirish kifoya:

    await check_and_increment_feature_limit(session, bot_id, "ommaviy_xabar", daily_limit=1)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feature_usage import FeatureUsageLog
from app.services.limits import LimitExceededError, today_tashkent


async def get_feature_usage_count(session: AsyncSession, bot_id: int, feature_key: str) -> int:
    """Joriy kun uchun shu funksiyadan necha marta foydalanilganini qaytaradi
    (hech qachon oshirmasdan — faqat o'qish uchun, masalan UI'da "3/10
    ishlatildi" ko'rsatish uchun)."""
    today = today_tashkent()
    result = await session.execute(
        select(FeatureUsageLog).where(
            FeatureUsageLog.bot_id == bot_id,
            FeatureUsageLog.feature_key == feature_key,
            FeatureUsageLog.date == today,
        )
    )
    log_row = result.scalar_one_or_none()
    return log_row.count if log_row else 0


async def check_and_increment_feature_limit(
    session: AsyncSession, bot_id: int, feature_key: str, daily_limit: int
) -> None:
    """Limitga yetgan bo'lsa LimitExceededError ko'taradi, aks holda
    hisoblagichni +1 qiladi va commit qiladi."""
    today = today_tashkent()
    result = await session.execute(
        select(FeatureUsageLog).where(
            FeatureUsageLog.bot_id == bot_id,
            FeatureUsageLog.feature_key == feature_key,
            FeatureUsageLog.date == today,
        )
    )
    log_row = result.scalar_one_or_none()
    current_count = log_row.count if log_row else 0

    if current_count >= daily_limit:
        raise LimitExceededError(f"Kunlik limit tugagan ({feature_key}): {current_count}/{daily_limit}")

    if log_row is None:
        session.add(FeatureUsageLog(bot_id=bot_id, feature_key=feature_key, date=today, count=1))
    else:
        log_row.count = current_count + 1

    await session.commit()
