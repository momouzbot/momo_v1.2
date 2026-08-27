"""
Bot egasini aniqlash — owner-only buyruqlar uchun (masalan kino qo'shish).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot as BotModel
from app.models.user import User


async def is_bot_owner(session: AsyncSession, bot_id: int, telegram_user_id: int) -> bool:
    result = await session.execute(
        select(User.telegram_id)
        .join(BotModel, BotModel.owner_id == User.id)
        .where(BotModel.id == bot_id)
    )
    owner_telegram_id = result.scalar_one_or_none()
    return owner_telegram_id == telegram_user_id
