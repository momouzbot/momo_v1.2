"""
BotRegistry — bitta process ichida barcha faol mijoz botlarining
aiogram Bot/Dispatcher juftliklarini xotirada saqlaydi (lazy-load).

TZ 2.1-bo'lim: "Bitta process ichida barcha faol botlarning Bot obyektlari
boshqariladi (lazy-load yoki xotirada saqlash)".
"""
from __future__ import annotations

import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot as BotModel
from app.models.base import ModuleType

logger = logging.getLogger(__name__)


class BotInstance:
    """Bitta mijoz botiga tegishli aiogram obyektlari + DB metama'lumot."""

    __slots__ = ("bot_row", "aiogram_bot", "dispatcher")

    def __init__(self, bot_row: BotModel, aiogram_bot: AiogramBot, dispatcher: Dispatcher):
        self.bot_row = bot_row
        self.aiogram_bot = aiogram_bot
        self.dispatcher = dispatcher


class BotRegistry:
    """
    In-memory kesh: telegram_bot_id -> BotInstance.

    Eslatma: bitta process, ko'p worker sxemasida bu kesh worker'lar orasida
    umumiy bo'lmaydi — shu sababli production'da "sticky routing" (bir bot_id
    doim bir worker'ga tushishi) yoki tashqi shared-cache (Redis) qo'llash
    tavsiya etiladi. MVP bosqichida bitta worker yetarli.
    """

    def __init__(self) -> None:
        self._instances: dict[int, BotInstance] = {}

    def get(self, telegram_bot_id: int) -> BotInstance | None:
        return self._instances.get(telegram_bot_id)

    def is_loaded(self, telegram_bot_id: int) -> bool:
        return telegram_bot_id in self._instances

    async def load(self, bot_row: BotModel, token: str) -> BotInstance:
        """Bot birinchi marta ishlatilganda chaqiriladi — xotiraga yuklaydi."""
        from app.modules.registry import get_module_class  # local import — circular import oldini olish

        aiogram_bot = AiogramBot(token=token)
        dp = Dispatcher()

        # Har bir update uchun DB session inject qilinadi (barcha modul handlerlari
        # `session: AsyncSession` argumentini olishi mumkin bo'ladi).
        from app.dispatcher.middleware import DBSessionMiddleware

        dp.update.middleware(DBSessionMiddleware())

        module_cls = get_module_class(ModuleType(bot_row.module_type))
        module = module_cls(bot_row=bot_row)
        module.register_handlers(dp)

        instance = BotInstance(bot_row=bot_row, aiogram_bot=aiogram_bot, dispatcher=dp)
        self._instances[bot_row.telegram_bot_id] = instance
        logger.info("Bot yuklandi: telegram_bot_id=%s module_type=%s", bot_row.telegram_bot_id, bot_row.module_type)
        return instance

    def unload(self, telegram_bot_id: int) -> None:
        """Bot o'chirilganda/to'xtatilganda xotiradan tozalash."""
        self._instances.pop(telegram_bot_id, None)


# Butun ilova bo'yicha yagona registry (singleton)
bot_registry = BotRegistry()
