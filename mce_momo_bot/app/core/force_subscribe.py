"""
Majburiy obuna (force-subscribe) — TZ 3.2-bo'lim.

bot_row.force_subscribe_channels — kanal username'lari ro'yxati (masalan
["@kanal1", "@kanal2"]), vergul bilan ajratilgan CSV ko'rinishida saqlanadi
(app/models/bot.py da String ustuni; keyinchalik alohida jadvalga chiqarilishi
mumkin, hozircha MVP uchun yetarli).

Middleware har bir message/callback_query'dan oldin ishlaydi: agar
foydalanuvchi barcha kanallarga obuna bo'lmagan bo'lsa, obuna tugmalari va
"✅ Tekshirish" tugmasi bilan xabar yuboradi va handlerga o'tkazmaydi.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram import Bot as AiogramBot
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.bot import Bot as BotModel

logger = logging.getLogger(__name__)


def _parse_channels(bot_row: BotModel) -> list[str]:
    raw = bot_row.force_subscribe_channels
    if not raw:
        return []
    if isinstance(raw, list):
        return [c.strip() for c in raw if c.strip()]
    # DB ustunida CSV-string sifatida kelishi ham mumkin
    return [c.strip() for c in str(raw).split(",") if c.strip()]


async def _user_subscribed_to_all(bot: AiogramBot, channels: list[str], user_id: int) -> list[str]:
    """Obuna bo'linmagan kanallar ro'yxatini qaytaradi (bo'sh bo'lsa — hammasiga obuna)."""
    missing: list[str] = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ("left", "kicked"):
                missing.append(channel)
        except Exception:
            # Bot kanalda admin bo'lmasa yoki kanal noto'g'ri bo'lsa — tekshirib
            # bo'lmaydi, xavfsizlik uchun "obuna emas" deb hisoblanadi.
            logger.warning("Kanal obunasini tekshirib bo'lmadi: %s", channel)
            missing.append(channel)
    return missing


def _build_subscribe_keyboard(missing_channels: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for channel in missing_channels:
        handle = channel.lstrip("@")
        builder.row(InlineKeyboardButton(text=f"📢 {channel}", url=f"https://t.me/{handle}"))
    builder.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data="force_sub_check"))
    return builder.as_markup()


class ForceSubscribeMiddleware(BaseMiddleware):
    def __init__(self, bot_row: BotModel):
        self.bot_row = bot_row

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        channels = _parse_channels(self.bot_row)
        if not channels:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        bot: AiogramBot = data["bot"]
        missing = await _user_subscribed_to_all(bot, channels, user.id)

        if not missing:
            return await handler(event, data)

        # "Tekshirish" tugmasi shu callback orqali kelsa — bu handler emas,
        # register_force_subscribe ichidagi maxsus handler unga javob beradi.
        if isinstance(event, CallbackQuery) and event.data == "force_sub_check":
            return await handler(event, data)

        text = "⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:"
        keyboard = _build_subscribe_keyboard(missing)

        if isinstance(event, Message):
            await event.answer(text, reply_markup=keyboard)
        elif isinstance(event, CallbackQuery):
            await event.answer("Iltimos, avval kanallarga obuna bo'ling.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=keyboard)

        return None  # handlerga o'tkazilmaydi


def register_force_subscribe(dp: Dispatcher, bot_row: BotModel) -> None:
    middleware = ForceSubscribeMiddleware(bot_row)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)

    @dp.callback_query(lambda c: c.data == "force_sub_check")
    async def on_check(callback: CallbackQuery) -> None:
        channels = _parse_channels(bot_row)
        missing = await _user_subscribed_to_all(callback.bot, channels, callback.from_user.id)
        if missing:
            await callback.answer("❌ Hali hamma kanallarga obuna bo'lmadingiz.", show_alert=True)
            return
        await callback.answer("✅ Obuna tasdiqlandi, davom etishingiz mumkin!")
        if callback.message:
            await callback.message.delete()
