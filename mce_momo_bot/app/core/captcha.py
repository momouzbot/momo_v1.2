"""
Captcha — guruhga yangi a'zo qo'shilganda oddiy tasdiqlash, TZ 3.2-bo'lim.

Oqim:
    1. Yangi a'zo qo'shiladi -> bot uni cheklaydi (send_message huquqisiz)
    2. "✅ Men robot emasman" tugmali xabar yuboriladi
    3. Aynan o'sha foydalanuvchi tugmani bossa -> cheklov olib tashlanadi
    4. Belgilangan vaqt ichida (default 3 daqiqa) bosilmasa -> guruhdan chiqariladi

Eslatma: bot guruhda cheklash/chiqarish huquqiga ega (administrator) bo'lishi shart.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F
from aiogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.models.bot import Bot as BotModel

logger = logging.getLogger(__name__)

CAPTCHA_TIMEOUT_SECONDS = 180
_RESTRICTED_PERMISSIONS = ChatPermissions(can_send_messages=False)
_DEFAULT_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_other_messages=True,
)


def register_captcha(dp: Dispatcher, bot_row: BotModel) -> None:
    """
    Eslatma: captcha yoqilgan bo'lsa, welcome_message ham shu modul ichida
    (tasdiqlangandan keyin) yuboriladi — app/modules/base.py shu sababli
    captcha yoqilganda register_welcome'ni alohida chaqirmaydi.
    """
    @dp.message(F.new_chat_members)
    async def on_new_members(message: Message, bot: AiogramBot) -> None:
        for member in message.new_chat_members:
            if member.is_bot:
                continue

            try:
                await bot.restrict_chat_member(
                    chat_id=message.chat.id, user_id=member.id, permissions=_RESTRICTED_PERMISSIONS
                )
            except Exception:
                logger.warning(
                    "Foydalanuvchini cheklab bo'lmadi (bot admin emasmi?): chat=%s user=%s",
                    message.chat.id, member.id,
                )
                continue

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Men robot emasman", callback_data=f"captcha_ok:{member.id}")
                ]]
            )
            sent = await message.answer(
                f"👋 Xush kelibsiz, {member.full_name}!\n"
                f"Guruhda yozish uchun {CAPTCHA_TIMEOUT_SECONDS} soniya ichida tasdiqlang:",
                reply_markup=keyboard,
            )

            asyncio.create_task(
                _kick_if_not_confirmed(bot, message.chat.id, member.id, sent.message_id)
            )

    @dp.callback_query(F.data.startswith("captcha_ok:"))
    async def on_captcha_confirm(callback) -> None:  # noqa: ANN001 - aiogram CallbackQuery
        target_user_id = int(callback.data.split(":", 1)[1])

        if callback.from_user.id != target_user_id:
            await callback.answer("Bu tugma sizga tegishli emas.", show_alert=True)
            return

        try:
            await callback.bot.restrict_chat_member(
                chat_id=callback.message.chat.id,
                user_id=target_user_id,
                permissions=_DEFAULT_PERMISSIONS,
            )
        except Exception:
            logger.exception("Cheklovni olib tashlashda xato: user=%s", target_user_id)

        await callback.answer("✅ Tasdiqlandi! Xush kelibsiz.")
        await callback.message.delete()

        # Captcha o'zi new_chat_members hodisasini "egallaydi", shu sababli
        # welcome_message shu yerda, tasdiqlangandan keyin yuboriladi
        # (ikkita alohida new_chat_members handleri to'qnashmasligi uchun).
        if bot_row.welcome_message:
            text = bot_row.welcome_message.replace("{name}", callback.from_user.full_name)
            await callback.message.answer(text)


async def _kick_if_not_confirmed(bot: AiogramBot, chat_id: int, user_id: int, captcha_message_id: int) -> None:
    """Vaqt tugagach foydalanuvchi hali cheklangan holatda qolsa — guruhdan chiqariladi."""
    await asyncio.sleep(CAPTCHA_TIMEOUT_SECONDS)
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if member.status == "restricted":
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)  # kick, ban emas
            await bot.delete_message(chat_id=chat_id, message_id=captcha_message_id)
            logger.info("Captcha muddati o'tdi, foydalanuvchi chiqarildi: user=%s chat=%s", user_id, chat_id)
    except Exception:
        logger.debug("Captcha timeout tekshiruvida xato (ehtimol allaqachon tasdiqlangan)", exc_info=True)
