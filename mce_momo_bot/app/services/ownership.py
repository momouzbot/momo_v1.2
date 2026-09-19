"""
Bot egasini aniqlash — owner-only buyruqlar uchun (masalan majburiy kanal,
ommaviy xabar, sub-adminlarni boshqarish).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot as BotModel
from app.models.sub_admin import BotSubAdmin
from app.models.user import User


async def is_bot_owner(session: AsyncSession, bot_id: int, telegram_user_id: int) -> bool:
    result = await session.execute(
        select(User.telegram_id)
        .join(BotModel, BotModel.owner_id == User.id)
        .where(BotModel.id == bot_id)
    )
    owner_telegram_id = result.scalar_one_or_none()
    return owner_telegram_id == telegram_user_id


async def is_bot_owner_or_sub_admin(session: AsyncSession, bot_id: int, telegram_user_id: int) -> bool:
    """Owner YOKI shu botga tayinlangan sub-admin bo'lsa True. Kontent
    boshqarish amallari (kino qo'shish/o'chirish, murojaatga javob berish
    va h.k.) uchun ishlatiladi — bot sozlamalari (kanal, broadcast,
    sub-admin boshqaruvi) esa qat'iy is_bot_owner talab qiladi."""
    if await is_bot_owner(session, bot_id, telegram_user_id):
        return True

    result = await session.execute(
        select(BotSubAdmin.id).where(
            BotSubAdmin.bot_id == bot_id, BotSubAdmin.telegram_user_id == telegram_user_id
        )
    )
    return result.scalar_one_or_none() is not None
