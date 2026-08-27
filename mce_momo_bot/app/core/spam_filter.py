"""
Asosiy so'kinish/spam filtri — TZ 3.2-bo'lim.

Middleware sifatida amalga oshirilgan (handler emas): bu modul handlerlari
bilan aiogram routing tartibida raqobatlashmasligini kafolatlaydi — spam
aniqlansa xabar o'chiriladi va zanjir shu yerda to'xtaydi (handlerga
yetib bormaydi); aks holda shaffof tarzda davom etadi.

Hozircha taqiqlangan so'zlar ro'yxati kod ichida saqlanadi (MVP).
TODO: keyingi bosqichda `bot_banned_words` jadvaliga chiqarish va admin
panel orqali har bir bot uchun alohida sozlash imkonini berish.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import Message, TelegramObject

from app.models.bot import Bot as BotModel

logger = logging.getLogger(__name__)

_DEFAULT_BANNED_WORDS = [
    "спам", "реклама",  # namuna; to'liq so'zlar bazasi bilan almashtiriladi
]


def _contains_banned_word(text: str, banned_words: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in banned_words)


class SpamFilterMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text:
            if _contains_banned_word(event.text, _DEFAULT_BANNED_WORDS):
                try:
                    await event.delete()
                    logger.info("Spam xabar o'chirildi: chat=%s user=%s", event.chat.id, event.from_user.id)
                except Exception:
                    logger.warning("Spam xabarni o'chirib bo'lmadi (bot admin emasmi?)")
                return None  # handlerlarga o'tkazilmaydi

        return await handler(event, data)


def register_spam_filter(dp: Dispatcher, bot_row: BotModel) -> None:
    dp.message.middleware(SpamFilterMiddleware())
