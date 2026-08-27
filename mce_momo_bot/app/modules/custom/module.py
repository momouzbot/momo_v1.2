"""
CustomBotModule (`custom`) — TZ 4.6-bo'lim, konstruktor bot.
MVP: Buyruq → Javob, tugmali menyu konstruktori (custom_commands, custom_buttons).
Eslatma: yangi buyruq/tugma qo'shish tahrirlash limitiga kiradi, matn tahrirlash kirmaydi.
"""
from __future__ import annotations

from aiogram import Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.modules.base import BaseModule


class CustomModule(BaseModule):
    def register_handlers(self, dp: Dispatcher) -> None:
        router = Router(name=f"custom_{self.bot_row.id}")

        @router.message(CommandStart())
        async def cmd_start(message: Message) -> None:
            await message.answer("Bot ishga tushdi.")

        # TODO: custom_commands jadvalidan buyruqlarni dinamik ro'yxatdan o'tkazish,
        # custom_buttons orqali daraxtsimon menyu (chuqurlik <= 3) — TZ 4.6

        # Core funksiyalar (captcha/welcome) avval ro'yxatdan o'tadi — aks holda
        # quyidagi modul routeridagi umumiy fallback handler ularni "yutib qo'yadi".
        self.register_core_features(dp)
        dp.include_router(router)
