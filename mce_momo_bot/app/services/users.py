"""
Momo mijozini topish/yaratish — ro'yxatdan o'tish oqimida ishlatiladi.

Shuningdek, birinchi Momo Admin'ni avtomatik belgilash logikasi shu yerda:
agar foydalanuvchining telegram_id'si `settings.super_admin_telegram_id`
bilan mos kelsa, u avtomatik `is_momo_admin=True` qilib belgilanadi (har safar
tekshiriladi, shu sababli flag qandaydir sabab bilan yo'qolib qolsa ham
qayta tiklanadi).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    full_name: str | None = None,
) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    is_super_admin = (
        settings.super_admin_telegram_id is not None
        and telegram_id == settings.super_admin_telegram_id
    )

    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            is_momo_admin=is_super_admin,
        )
        session.add(user)
        await session.flush()  # user.id kerak bo'ladi (commit qilmasdan)
        return user

    # Mavjud foydalanuvchi ma'lumotlarini yangilab turish (username o'zgargan bo'lishi mumkin)
    changed = False
    if username is not None and user.username != username:
        user.username = username
        changed = True
    if full_name is not None and user.full_name != full_name:
        user.full_name = full_name
        changed = True
    if is_super_admin and not user.is_momo_admin:
        user.is_momo_admin = True
        changed = True
    if changed:
        await session.flush()

    return user
