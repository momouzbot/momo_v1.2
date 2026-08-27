"""
Modul faolligini tekshirish — admin panel orqali yoqilgan/o'chirilgan
modullarni boshqarish uchun (TZ 4.7 + foydalanuvchi so'rovi bo'yicha).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import ModuleType
from app.models.module import Module

DEVELOPMENT_NOTICE = (
    "🛠 Ushbu xizmat hozircha ishlab chiqilmoqda.\n"
    "Tez orada foydalanish mumkin bo'ladi. Kuzatib boring!"
)


async def is_module_active(session: AsyncSession, module_type: ModuleType) -> bool:
    result = await session.execute(select(Module.is_active).where(Module.code == module_type))
    is_active = result.scalar_one_or_none()
    # Modul jadvalida yozuv topilmasa — xavfsizlik uchun "faol emas" deb hisoblanadi
    return bool(is_active)


async def list_modules(session: AsyncSession) -> list[Module]:
    result = await session.execute(select(Module).order_by(Module.code))
    return list(result.scalars().all())


async def set_module_active(session: AsyncSession, module_type: ModuleType, is_active: bool) -> Module:
    result = await session.execute(select(Module).where(Module.code == module_type))
    module_row = result.scalar_one_or_none()
    if module_row is None:
        raise ValueError(f"Modul topilmadi: {module_type}")
    module_row.is_active = is_active
    await session.commit()
    await session.refresh(module_row)
    return module_row
