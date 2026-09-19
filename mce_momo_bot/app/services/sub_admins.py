"""
Sub-admin (yordamchi moderator) boshqaruvi — TZ: "kinobot moduli yakuniy
tahrir rejasi", umumiy (core) funksiya.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sub_admin import BotSubAdmin

SUB_ADMIN_LIMIT = 3


class SubAdminLimitError(Exception):
    """Bot boshiga maksimum SUB_ADMIN_LIMIT ta sub-admin — bu qat'iy cheklov."""


class SubAdminAlreadyExistsError(Exception):
    pass


async def list_sub_admins(session: AsyncSession, bot_id: int) -> list[BotSubAdmin]:
    result = await session.execute(
        select(BotSubAdmin).where(BotSubAdmin.bot_id == bot_id).order_by(BotSubAdmin.created_at)
    )
    return list(result.scalars().all())


async def add_sub_admin(
    session: AsyncSession,
    bot_id: int,
    telegram_user_id: int,
    added_by_telegram_id: int,
    full_name: str | None = None,
) -> BotSubAdmin:
    existing = await list_sub_admins(session, bot_id)
    if any(sa.telegram_user_id == telegram_user_id for sa in existing):
        raise SubAdminAlreadyExistsError("Bu foydalanuvchi allaqachon sub-admin.")
    if len(existing) >= SUB_ADMIN_LIMIT:
        raise SubAdminLimitError(f"Sub-admin limiti to'lgan: {len(existing)}/{SUB_ADMIN_LIMIT}")

    sub_admin = BotSubAdmin(
        bot_id=bot_id,
        telegram_user_id=telegram_user_id,
        full_name=full_name,
        added_by_telegram_id=added_by_telegram_id,
    )
    session.add(sub_admin)
    await session.commit()
    await session.refresh(sub_admin)
    return sub_admin


async def remove_sub_admin(session: AsyncSession, bot_id: int, telegram_user_id: int) -> None:
    result = await session.execute(
        select(BotSubAdmin).where(
            BotSubAdmin.bot_id == bot_id, BotSubAdmin.telegram_user_id == telegram_user_id
        )
    )
    sub_admin = result.scalar_one_or_none()
    if sub_admin is not None:
        await session.delete(sub_admin)
        await session.commit()
