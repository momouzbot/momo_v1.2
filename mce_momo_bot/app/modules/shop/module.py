"""
ShopModule (`shop`) — TZ 4.4-bo'lim.
Skeleton bosqichi: katalog, savat, buyurtma oqimi TZ 10-bo'lim,
7-qadamda amalga oshiriladi.
"""
from __future__ import annotations

from aiogram import Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.modules.base import BaseModule


class ShopModule(BaseModule):
    def register_handlers(self, dp: Dispatcher) -> None:
        router = Router(name=f"shop_{self.bot_row.id}")

        @router.message(CommandStart())
        async def cmd_start(message: Message) -> None:
            await message.answer("Do'kon-bot ishga tushdi. Katalogni ko'rish uchun /katalog yuboring.")

        # TODO: katalog/kategoriya panellari (⚠️ yangi panel = tahrirlash limitiga hisoblanadi,
        # TZ 6.2), savat tizimi, buyurtma shakllantirish va holat kuzatuvi (TZ 4.4)

        # Core funksiyalar (captcha/welcome) avval ro'yxatdan o'tadi — aks holda
        # quyidagi modul routeridagi umumiy fallback handler ularni "yutib qo'yadi".
        self.register_core_features(dp)
        dp.include_router(router)
