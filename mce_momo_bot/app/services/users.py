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
from app.models.base import TariffCode
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
    # full_name faqat ro'yxatdan o'tish oqimi TUGAMAGAN foydalanuvchilar uchun
    # Telegram profilidan avtomatik yangilanadi. Ro'yxatdan o'tishni tugatgan
    # mijoz o'zi kiritgan ismni saqlab qolishi kerak — Telegram profil nomi
    # o'zgarsa ham ustidan yozilmasin.
    if full_name is not None and user.full_name != full_name and not user.registration_completed:
        user.full_name = full_name
        changed = True
    if is_super_admin and not user.is_momo_admin:
        user.is_momo_admin = True
        changed = True
    if changed:
        await session.flush()

    return user


async def complete_registration(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    phone_number: str,
    preferred_tariff_code: TariffCode,
) -> User:
    """Qisqa ro'yxatdan o'tish oqimi (ism, telefon, ta'rif) yakunlanganda chaqiriladi."""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id)
        session.add(user)

    user.full_name = full_name
    user.phone_number = phone_number
    user.preferred_tariff_code = preferred_tariff_code
    user.registration_completed = True
    await session.flush()
    return user
