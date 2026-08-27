"""
AdminModule (`admin`) — TZ 4.1-bo'lim.
Skeleton bosqichi: to'liq funksionallik (avto-post, statistika, kengaytirilgan
spam filtri, taqiqlangan havolalar) TZ 10-bo'lim, 7-qadamda amalga oshiriladi.
"""
from __future__ import annotations

from aiogram import Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.modules.base import BaseModule


class AdminModule(BaseModule):
    def register_handlers(self, dp: Dispatcher) -> None:
        router = Router(name=f"admin_{self.bot_row.id}")

        @router.message(CommandStart())
        async def cmd_start(message: Message) -> None:
            await message.answer("Admin-bot ishga tushdi. Boshqaruv paneli tez orada qo'shiladi.")

        # TODO: avto-post scheduler (TZ 4.1), a'zolar statistikasi,
        # kengaytirilgan spam filtri/avtoban, taqiqlangan havolalarni o'chirish

        # Core funksiyalar (captcha/welcome) avval ro'yxatdan o'tadi — aks holda
        # quyidagi modul routeridagi umumiy fallback handler ularni "yutib qo'yadi".
        self.register_core_features(dp)
        dp.include_router(router)
