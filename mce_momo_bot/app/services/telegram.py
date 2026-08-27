"""
Bot token validatsiyasi va webhook o'rnatish/o'chirish — TZ 5-bo'lim
(Bot yaratish oqimi) va 11-bo'lim (token noto'g'ri bo'lsa aniq xato xabari).
"""
from __future__ import annotations

import logging

from aiogram import Bot as AiogramBot
from aiogram.exceptions import TelegramUnauthorizedError

from app.config import settings

logger = logging.getLogger(__name__)


class InvalidTokenError(Exception):
    """Token noto'g'ri yoki eskirgan (TZ 11-bo'lim)."""


class TelegramMeInfo:
    __slots__ = ("bot_id", "username", "first_name")

    def __init__(self, bot_id: int, username: str, first_name: str):
        self.bot_id = bot_id
        self.username = username
        self.first_name = first_name


async def validate_token(raw_token: str) -> TelegramMeInfo:
    """
    Telegram getMe orqali tokenni tekshiradi.
    Noto'g'ri bo'lsa InvalidTokenError ko'taradi — aniq xato xabari uchun.
    """
    bot = AiogramBot(token=raw_token)
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError as exc:
        raise InvalidTokenError("Bot tokeni noto'g'ri yoki eskirgan.") from exc
    finally:
        await bot.session.close()

    return TelegramMeInfo(bot_id=me.id, username=me.username or "", first_name=me.first_name)


async def set_webhook(raw_token: str, telegram_bot_id: int) -> None:
    """Berilgan bot uchun webhook manzilini Telegram'da o'rnatadi."""
    bot = AiogramBot(token=raw_token)
    try:
        url = settings.webhook_url_for(str(telegram_bot_id))
        await bot.set_webhook(url=url, drop_pending_updates=True)
        logger.info("Webhook o'rnatildi: bot_id=%s url=%s", telegram_bot_id, url)
    finally:
        await bot.session.close()


async def delete_webhook(raw_token: str) -> None:
    """Bot to'xtatilganda/o'chirilganda webhookni olib tashlaydi (TZ 6.4, 6.5)."""
    bot = AiogramBot(token=raw_token)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    finally:
        await bot.session.close()
